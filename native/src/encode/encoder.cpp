#include "snowlink/encoder.h"

#include <Windows.h>
#include <strmif.h>
#include <codecapi.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <wrl/client.h>
#include <algorithm>
#include <cctype>
#include <limits>

using Microsoft::WRL::ComPtr;

namespace snowlink {
namespace {

std::string narrow(const wchar_t* value) {
    if (!value) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
    std::string result(size > 0 ? static_cast<size_t>(size - 1) : 0, '\0');
    if (size > 1) WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), size - 1, nullptr, nullptr);
    return result;
}

std::string vendor_from_name(const std::string& name) {
    std::string lower = name;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (lower.find("nvidia") != std::string::npos) return "NVIDIA";
    if (lower.find("intel") != std::string::npos) return "Intel";
    if (lower.find("amd") != std::string::npos || lower.find("advanced micro") != std::string::npos) return "AMD";
    if (lower.find("microsoft") != std::string::npos) return "Microsoft";
    return "Unknown";
}

HRESULT set_u32(ICodecAPI* api, const GUID& key, ULONG value) {
    if (!api) return E_NOINTERFACE;
    VARIANT v{}; VariantInit(&v); v.vt = VT_UI4; v.ulVal = value;
    const HRESULT hr = api->SetValue(&key, &v); VariantClear(&v); return hr;
}

HRESULT set_bool(ICodecAPI* api, const GUID& key, bool value) {
    if (!api) return E_NOINTERFACE;
    VARIANT v{}; VariantInit(&v); v.vt = VT_BOOL; v.boolVal = value ? VARIANT_TRUE : VARIANT_FALSE;
    const HRESULT hr = api->SetValue(&key, &v); VariantClear(&v); return hr;
}

} // namespace

class H264HardwareEncoder::State {
public:
    EncoderSettings settings{};
    EncoderInfo info{};
    ComPtr<ID3D11Device> device;
    ComPtr<IMFDXGIDeviceManager> device_manager;
    UINT device_token = 0;
    ComPtr<IMFTransform> transform;
    ComPtr<IMFMediaEventGenerator> event_generator;
    ComPtr<ICodecAPI> codec_api;
    DWORD input_stream = 0;
    DWORD output_stream = 0;
    MFT_OUTPUT_STREAM_INFO output_info{};
    bool mf_started = false;
    bool com_initialized = false;
    bool initialized = false;
    bool asynchronous = false;
    bool need_input = false;
    std::uint64_t frame_duration = 0;

    HRESULT choose_transform(bool hardware_only, IMFActivate** selected, bool& hardware) {
        MFT_REGISTER_TYPE_INFO input{MFMediaType_Video, MFVideoFormat_NV12};
        MFT_REGISTER_TYPE_INFO output{MFMediaType_Video, MFVideoFormat_H264};
        IMFActivate** activates = nullptr; UINT32 count = 0;
        UINT32 flags = MFT_ENUM_FLAG_SORTANDFILTER | MFT_ENUM_FLAG_LOCALMFT;
        flags |= hardware_only ? MFT_ENUM_FLAG_HARDWARE : MFT_ENUM_FLAG_SYNCMFT;
        HRESULT hr = MFTEnumEx(MFT_CATEGORY_VIDEO_ENCODER, flags, &input, &output, &activates, &count);
        if (FAILED(hr)) return hr;
        if (!count) { CoTaskMemFree(activates); return MF_E_TOPO_CODEC_NOT_FOUND; }
        *selected = activates[0]; (*selected)->AddRef();
        hardware = hardware_only;
        for (UINT32 i = 0; i < count; ++i) activates[i]->Release();
        CoTaskMemFree(activates);
        return S_OK;
    }

    HRESULT configure_types() {
        DWORD in_count = 0, out_count = 0;
        HRESULT hr = transform->GetStreamCount(&in_count, &out_count);
        if (FAILED(hr) || !in_count || !out_count) return FAILED(hr) ? hr : E_UNEXPECTED;
        DWORD in_id = 0, out_id = 0;
        if (SUCCEEDED(transform->GetStreamIDs(1, &in_id, 1, &out_id))) {
            input_stream = in_id; output_stream = out_id;
        }

        ComPtr<IMFMediaType> out_type;
        if (FAILED(hr = MFCreateMediaType(&out_type)) ||
            FAILED(hr = out_type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video)) ||
            FAILED(hr = out_type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264)) ||
            FAILED(hr = MFSetAttributeSize(out_type.Get(), MF_MT_FRAME_SIZE, settings.width, settings.height)) ||
            FAILED(hr = MFSetAttributeRatio(out_type.Get(), MF_MT_FRAME_RATE, settings.fps, 1)) ||
            FAILED(hr = MFSetAttributeRatio(out_type.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1)) ||
            FAILED(hr = out_type->SetUINT32(MF_MT_AVG_BITRATE, settings.bitrate)) ||
            FAILED(hr = out_type->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive)) ||
            FAILED(hr = out_type->SetUINT32(MF_MT_MPEG2_PROFILE, eAVEncH264VProfile_Main)) ||
            FAILED(hr = transform->SetOutputType(output_stream, out_type.Get(), 0))) return hr;

        ComPtr<IMFMediaType> in_type;
        if (FAILED(hr = MFCreateMediaType(&in_type)) ||
            FAILED(hr = in_type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video)) ||
            FAILED(hr = in_type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12)) ||
            FAILED(hr = MFSetAttributeSize(in_type.Get(), MF_MT_FRAME_SIZE, settings.width, settings.height)) ||
            FAILED(hr = MFSetAttributeRatio(in_type.Get(), MF_MT_FRAME_RATE, settings.fps, 1)) ||
            FAILED(hr = MFSetAttributeRatio(in_type.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1)) ||
            FAILED(hr = in_type->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive)) ||
            FAILED(hr = transform->SetInputType(input_stream, in_type.Get(), 0))) return hr;
        return transform->GetOutputStreamInfo(output_stream, &output_info);
    }

    HRESULT drain(std::vector<EncodedFrame>& frames) {
        for (;;) {
            ComPtr<IMFSample> sample;
            if (!(output_info.dwFlags & MFT_OUTPUT_STREAM_PROVIDES_SAMPLES)) {
                HRESULT hr = MFCreateSample(&sample); if (FAILED(hr)) return hr;
                ComPtr<IMFMediaBuffer> buffer;
                const DWORD capacity = std::max<DWORD>(output_info.cbSize, std::max<DWORD>(1'048'576, settings.width * settings.height));
                if (FAILED(hr = MFCreateMemoryBuffer(capacity, &buffer)) || FAILED(hr = sample->AddBuffer(buffer.Get()))) return hr;
            }
            MFT_OUTPUT_DATA_BUFFER data{}; data.dwStreamID = output_stream; data.pSample = sample.Get();
            DWORD status = 0; const HRESULT hr = transform->ProcessOutput(0, 1, &data, &status);
            if (data.pEvents) data.pEvents->Release();
            if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) return S_OK;
            if (FAILED(hr)) return hr;
            ComPtr<IMFSample> returned_sample;
            if (data.pSample && data.pSample != sample.Get()) returned_sample.Attach(data.pSample);
            IMFSample* produced = data.pSample ? data.pSample : sample.Get();
            if (!produced) return E_UNEXPECTED;
            ComPtr<IMFMediaBuffer> contiguous;
            if (FAILED(produced->ConvertToContiguousBuffer(&contiguous))) return E_FAIL;
            BYTE* bytes = nullptr; DWORD length = 0;
            HRESULT lock_hr = contiguous->Lock(&bytes, nullptr, &length);
            if (FAILED(lock_hr)) return lock_hr;
            EncodedFrame frame; frame.codec = VideoCodec::H264;
            LONGLONG time = 0; if (SUCCEEDED(produced->GetSampleTime(&time))) frame.timestamp = static_cast<uint64_t>(time);
            UINT32 clean = FALSE; frame.keyframe = SUCCEEDED(produced->GetUINT32(MFSampleExtension_CleanPoint, &clean)) && clean;
            frame.bytes.assign(bytes, bytes + length);
            contiguous->Unlock(); frames.push_back(std::move(frame));
            if (!(status & MFT_OUTPUT_DATA_BUFFER_INCOMPLETE)) return S_OK;
        }
    }

    HRESULT pump_events(std::vector<EncodedFrame>& frames) {
        if (!asynchronous) return S_OK;
        for (;;) {
            ComPtr<IMFMediaEvent> event;
            const HRESULT event_hr = event_generator->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event);
            if (event_hr == MF_E_NO_EVENTS_AVAILABLE) return S_OK;
            if (FAILED(event_hr)) return event_hr;
            MediaEventType type = MEUnknown; HRESULT status = S_OK;
            event->GetType(&type); event->GetStatus(&status);
            if (FAILED(status)) return status;
            if (type == METransformNeedInput) need_input = true;
            else if (type == METransformHaveOutput) {
                const HRESULT hr = drain(frames); if (FAILED(hr)) return hr;
            }
        }
    }
};

H264HardwareEncoder::H264HardwareEncoder() : state_(std::make_unique<State>()) {}
H264HardwareEncoder::~H264HardwareEncoder() { shutdown(); }

int32_t H264HardwareEncoder::initialize(ID3D11Device* device, const EncoderSettings& settings) {
    shutdown();
    if (!device || !settings.width || !settings.height || !settings.fps || !settings.bitrate ||
        (settings.width & 1) || (settings.height & 1)) return E_INVALIDARG;
    state_->settings = settings; state_->device = device;
    HRESULT com_hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (SUCCEEDED(com_hr)) state_->com_initialized = true;
    else if (com_hr != RPC_E_CHANGED_MODE) return com_hr;
    HRESULT hr = MFStartup(MF_VERSION, MFSTARTUP_LITE); if (FAILED(hr)) { shutdown(); return hr; }
    state_->mf_started = true;
    ComPtr<IMFActivate> activate; bool hardware = false;
    hr = state_->choose_transform(true, &activate, hardware);
    if (FAILED(hr) && settings.hardware_preference == HardwarePreference::AllowSoftwareFallback)
        hr = state_->choose_transform(false, &activate, hardware);
    if (FAILED(hr)) { shutdown(); return hr; }
    WCHAR* friendly = nullptr; UINT32 chars = 0;
    activate->GetAllocatedString(MFT_FRIENDLY_NAME_Attribute, &friendly, &chars);
    state_->info.encoder_name = narrow(friendly); CoTaskMemFree(friendly);
    state_->info.encoder_vendor = vendor_from_name(state_->info.encoder_name);
    state_->info.hardware_accelerated = hardware;
    if (FAILED(hr = activate->ActivateObject(IID_PPV_ARGS(&state_->transform)))) { shutdown(); return hr; }
    state_->asynchronous = SUCCEEDED(state_->transform.As(&state_->event_generator));

    if (hardware) {
        if (FAILED(hr = MFCreateDXGIDeviceManager(&state_->device_token, &state_->device_manager)) ||
            FAILED(hr = state_->device_manager->ResetDevice(device, state_->device_token)) ||
            FAILED(hr = state_->transform->ProcessMessage(MFT_MESSAGE_SET_D3D_MANAGER,
                reinterpret_cast<ULONG_PTR>(state_->device_manager.Get())))) { shutdown(); return hr; }
    }
    ComPtr<IMFAttributes> attrs;
    if (SUCCEEDED(state_->transform->GetAttributes(&attrs))) {
        attrs->SetUINT32(MF_LOW_LATENCY, settings.low_latency ? TRUE : FALSE);
        attrs->SetUINT32(MF_TRANSFORM_ASYNC_UNLOCK, TRUE);
    }
    state_->transform.As(&state_->codec_api);
    set_u32(state_->codec_api.Get(), CODECAPI_AVEncCommonRateControlMode,
            settings.rate_control == RateControlMode::Cbr ? eAVEncCommonRateControlMode_CBR : eAVEncCommonRateControlMode_UnconstrainedVBR);
    set_u32(state_->codec_api.Get(), CODECAPI_AVEncCommonMeanBitRate, settings.bitrate);
    set_u32(state_->codec_api.Get(), CODECAPI_AVEncMPVGOPSize, settings.keyframe_interval);
    set_u32(state_->codec_api.Get(), CODECAPI_AVEncVideoMaxNumRefFrame, 1);
    set_bool(state_->codec_api.Get(), CODECAPI_AVLowLatencyMode, settings.low_latency);
    if (FAILED(hr = state_->configure_types()) ||
        FAILED(hr = state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0)) ||
        FAILED(hr = state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0))) { shutdown(); return hr; }
    state_->frame_duration = 10'000'000ULL / settings.fps;
    state_->info.profile = "Main"; state_->info.width = settings.width; state_->info.height = settings.height;
    state_->info.fps = settings.fps; state_->info.bitrate = settings.bitrate; state_->initialized = true;
    return S_OK;
}

int32_t H264HardwareEncoder::encode(ID3D11Texture2D* texture, std::uint64_t timestamp,
                                    std::vector<EncodedFrame>& output) {
    if (!state_->initialized || !texture) return MF_E_NOT_INITIALIZED;
    D3D11_TEXTURE2D_DESC desc{}; texture->GetDesc(&desc);
    if (desc.Format != DXGI_FORMAT_NV12 || desc.Width != state_->settings.width || desc.Height != state_->settings.height)
        return E_INVALIDARG;
    ComPtr<ID3D11Device> input_device; texture->GetDevice(&input_device);
    if (input_device.Get() != state_->device.Get()) return E_INVALIDARG;
    HRESULT hr = state_->pump_events(output); if (FAILED(hr)) return hr;
    if (state_->asynchronous && !state_->need_input) return S_FALSE; // bounded latest-frame drop
    ComPtr<IMFMediaBuffer> buffer; hr = MFCreateDXGISurfaceBuffer(__uuidof(ID3D11Texture2D), texture, 0, FALSE, &buffer);
    ComPtr<IMFSample> sample;
    if (FAILED(hr) || FAILED(hr = MFCreateSample(&sample)) || FAILED(hr = sample->AddBuffer(buffer.Get())) ||
        FAILED(hr = sample->SetSampleTime(static_cast<LONGLONG>(timestamp))) ||
        FAILED(hr = sample->SetSampleDuration(static_cast<LONGLONG>(state_->frame_duration)))) return hr;
    hr = state_->transform->ProcessInput(state_->input_stream, sample.Get(), 0);
    if (hr == MF_E_NOTACCEPTING) {
        if (FAILED(hr = state_->drain(output))) return hr;
        hr = state_->transform->ProcessInput(state_->input_stream, sample.Get(), 0);
    }
    if (FAILED(hr)) return hr;
    if (state_->asynchronous) {
        state_->need_input = false;
        return state_->pump_events(output);
    }
    return state_->drain(output);
}

int32_t H264HardwareEncoder::request_keyframe() {
    if (!state_->initialized) return MF_E_NOT_INITIALIZED;
    return set_bool(state_->codec_api.Get(), CODECAPI_AVEncVideoForceKeyFrame, true);
}

int32_t H264HardwareEncoder::set_bitrate(std::uint32_t bitrate) {
    if (!state_->initialized || !bitrate) return E_INVALIDARG;
    const HRESULT hr = set_u32(state_->codec_api.Get(), CODECAPI_AVEncCommonMeanBitRate, bitrate);
    if (SUCCEEDED(hr)) { state_->settings.bitrate = bitrate; state_->info.bitrate = bitrate; }
    return hr;
}

int32_t H264HardwareEncoder::set_fps(std::uint32_t fps) {
    if (!state_->initialized || !fps) return E_INVALIDARG;
    // Most hardware MFTs accept timestamps at a new cadence without renegotiation.
    // Updating the advertised media type mid-stream is driver-specific, so keep
    // the negotiated maximum and change duration/cadence only.
    state_->settings.fps = fps; state_->info.fps = fps; state_->frame_duration = 10'000'000ULL / fps;
    return S_OK;
}

void H264HardwareEncoder::shutdown() {
    if (!state_) return;
    if (state_->transform) {
        state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_END_OF_STREAM, 0);
        state_->transform->ProcessMessage(MFT_MESSAGE_COMMAND_FLUSH, 0);
        state_->transform->ProcessMessage(MFT_MESSAGE_NOTIFY_END_STREAMING, 0);
    }
    state_->codec_api.Reset(); state_->event_generator.Reset(); state_->transform.Reset(); state_->device_manager.Reset(); state_->device.Reset();
    state_->initialized = false;
    if (state_->mf_started) { MFShutdown(); state_->mf_started = false; }
    if (state_->com_initialized) { CoUninitialize(); state_->com_initialized = false; }
}

const EncoderInfo& H264HardwareEncoder::info() const noexcept { return state_->info; }

} // namespace snowlink
