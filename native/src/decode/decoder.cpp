#include "snowlink/decoder.h"
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <codecapi.h>
#include <wrl/client.h>
#include <chrono>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace snowlink {

class H264HardwareDecoder::State {
public:
    ComPtr<ID3D11Device> device;
    ComPtr<IMFDXGIDeviceManager> manager;
    ComPtr<IMFTransform> transform;
    DecoderInfo info;
    UINT reset_token = 0;
    std::chrono::steady_clock::time_point rate_mark{};
    std::uint64_t rate_frames = 0;
};

namespace {

HRESULT find_h264_decoder(IMFActivate*** activations, UINT* count, bool& hardware) {
    MFT_REGISTER_TYPE_INFO input{MFMediaType_Video, MFVideoFormat_H264};
    hardware = true;
    HRESULT hr = MFTEnumEx(
        MFT_CATEGORY_VIDEO_DECODER,
        MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER,
        &input, nullptr, activations, count);
    if (SUCCEEDED(hr) && *count != 0) return S_OK;
    if (*activations) {
        CoTaskMemFree(*activations);
        *activations = nullptr;
    }
    *count = 0;

    // The Microsoft H.264 decoder is normally registered as a synchronous MFT,
    // even when it performs DXVA decoding into D3D11 surfaces.  Restricting the
    // search to MFT_ENUM_FLAG_HARDWARE therefore rejects valid decoder setups.
    hardware = false;
    return MFTEnumEx(
        MFT_CATEGORY_VIDEO_DECODER,
        MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_ASYNCMFT |
            MFT_ENUM_FLAG_LOCALMFT | MFT_ENUM_FLAG_SORTANDFILTER,
        &input, nullptr, activations, count);
}

} // namespace

H264HardwareDecoder::H264HardwareDecoder() : state_(std::make_unique<State>()) {}
H264HardwareDecoder::~H264HardwareDecoder() { shutdown(); }

int32_t H264HardwareDecoder::initialize(ID3D11Device* device) {
    shutdown();
    if (!device) return E_INVALIDARG;
    HRESULT hr = MFStartup(MF_VERSION, MFSTARTUP_LITE);
    if (FAILED(hr)) return hr;
    state_->device = device;
    ComPtr<ID3D10Multithread> multithread;
    if (SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&multithread)))) multithread->SetMultithreadProtected(TRUE);
    if (FAILED(hr = MFCreateDXGIDeviceManager(&state_->reset_token, &state_->manager)) ||
        FAILED(hr = state_->manager->ResetDevice(device, state_->reset_token))) return hr;

    IMFActivate** activations = nullptr; UINT count = 0;
    bool hardware = false;
    hr = find_h264_decoder(&activations, &count, hardware);
    if (FAILED(hr) || count == 0) { CoTaskMemFree(activations); return MF_E_TOPO_CODEC_NOT_FOUND; }
    WCHAR* name = nullptr; UINT name_len = 0;
    activations[0]->GetAllocatedString(MFT_FRIENDLY_NAME_Attribute, &name, &name_len);
    if (name) { int n = WideCharToMultiByte(CP_UTF8, 0, name, -1, nullptr, 0, nullptr, nullptr);
        std::vector<char> s(static_cast<size_t>(n)); WideCharToMultiByte(CP_UTF8, 0, name, -1, s.data(), n, nullptr, nullptr);
        state_->info.decoder_name = s.data(); CoTaskMemFree(name); }
    hr = activations[0]->ActivateObject(IID_PPV_ARGS(&state_->transform));
    for (UINT i = 0; i < count; ++i) activations[i]->Release(); CoTaskMemFree(activations);
    if (FAILED(hr)) return hr;
    state_->info.hardware_accelerated = hardware;
    ComPtr<IMFAttributes> attrs;
    if (SUCCEEDED(state_->transform->GetAttributes(&attrs))) {
        attrs->SetUINT32(MF_LOW_LATENCY, TRUE);
        attrs->SetUINT32(MF_SA_D3D11_AWARE, TRUE);
    }
    if (FAILED(hr = state_->transform->ProcessMessage(MFT_MESSAGE_SET_D3D_MANAGER,
        reinterpret_cast<ULONG_PTR>(state_->manager.Get())))) return hr;
    ComPtr<IMFMediaType> input_type;
    if (FAILED(hr = MFCreateMediaType(&input_type)) ||
        FAILED(hr = input_type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video)) ||
        FAILED(hr = input_type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264)) ||
        FAILED(hr = state_->transform->SetInputType(0, input_type.Get(), 0))) return hr;
    return state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
}

int32_t H264HardwareDecoder::decode(const EncodedFrame& frame, ID3D11Texture2D** texture) {
    if (!texture || !state_->transform || frame.bytes.empty()) return E_INVALIDARG;
    *texture = nullptr;
    ComPtr<IMFSample> sample; ComPtr<IMFMediaBuffer> buffer;
    HRESULT hr = MFCreateSample(&sample);
    if (FAILED(hr) || FAILED(hr = MFCreateMemoryBuffer(static_cast<DWORD>(frame.bytes.size()), &buffer))) return hr;
    BYTE* dst = nullptr; DWORD capacity = 0;
    if (FAILED(hr = buffer->Lock(&dst, &capacity, nullptr))) return hr;
    memcpy(dst, frame.bytes.data(), frame.bytes.size()); buffer->Unlock();
    buffer->SetCurrentLength(static_cast<DWORD>(frame.bytes.size())); sample->AddBuffer(buffer.Get());
    sample->SetSampleTime(static_cast<LONGLONG>(frame.timestamp));
    if (FAILED(hr = state_->transform->ProcessInput(0, sample.Get(), 0))) { ++state_->info.corrupt_frames; return hr; }

    MFT_OUTPUT_STREAM_INFO stream{};
    if (FAILED(hr = state_->transform->GetOutputStreamInfo(0, &stream))) return hr;
    MFT_OUTPUT_DATA_BUFFER output{}; output.dwStreamID = 0;
    DWORD status = 0;
    hr = state_->transform->ProcessOutput(0, 1, &output, &status);
    if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
        for (DWORD index = 0;; ++index) {
            ComPtr<IMFMediaType> type;
            if (FAILED(state_->transform->GetOutputAvailableType(0, index, &type))) break;
            GUID subtype{}; type->GetGUID(MF_MT_SUBTYPE, &subtype);
            if (subtype == MFVideoFormat_NV12 && SUCCEEDED(state_->transform->SetOutputType(0, type.Get(), 0))) {
                UINT64 size = 0; type->GetUINT64(MF_MT_FRAME_SIZE, &size);
                state_->info.decoded_width = static_cast<UINT32>(size >> 32);
                state_->info.decoded_height = static_cast<UINT32>(size); break;
            }
        }
        hr = state_->transform->ProcessOutput(0, 1, &output, &status);
    }
    if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) return S_FALSE;
    if (FAILED(hr)) { ++state_->info.corrupt_frames; return hr; }
    ComPtr<IMFSample> decoded; decoded.Attach(output.pSample);
    if (output.pEvents) output.pEvents->Release();
    if (!decoded) return S_FALSE;
    ComPtr<IMFMediaBuffer> decoded_buffer; decoded->GetBufferByIndex(0, &decoded_buffer);
    ComPtr<IMFDXGIBuffer> dxgi; if (!decoded_buffer || FAILED(decoded_buffer.As(&dxgi))) return MF_E_UNSUPPORTED_D3D_TYPE;
    hr = dxgi->GetResource(IID_PPV_ARGS(texture));
    if (SUCCEEDED(hr)) {
        ++state_->info.frames_decoded; ++state_->rate_frames;
        const auto now = std::chrono::steady_clock::now();
        if (state_->rate_mark.time_since_epoch().count() == 0) state_->rate_mark = now;
        const double seconds = std::chrono::duration<double>(now - state_->rate_mark).count();
        if (seconds >= 0.5) { state_->info.decode_fps = state_->rate_frames / seconds; state_->rate_frames = 0; state_->rate_mark = now; }
    }
    return hr;
}

int32_t H264HardwareDecoder::reset() {
    if (!state_->transform) return S_OK;
    HRESULT hr = state_->transform->ProcessMessage(MFT_MESSAGE_COMMAND_FLUSH, 0);
    if (SUCCEEDED(hr)) hr = state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
    return hr;
}
void H264HardwareDecoder::shutdown() { if (state_->transform) state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_END_STREAMING, 0); state_->transform.Reset(); state_->manager.Reset(); state_->device.Reset(); }
const DecoderInfo& H264HardwareDecoder::info() const noexcept { return state_->info; }

} // namespace snowlink
