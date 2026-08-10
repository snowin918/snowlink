#include "snowlink/renderer.h"
#include <dxgi1_2.h>
#include <wrl/client.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

using Microsoft::WRL::ComPtr;
namespace snowlink {
class Renderer::State {
public:
    HWND hwnd{}; ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain1> swap; ComPtr<ID3D11VideoDevice> video_device; ComPtr<ID3D11VideoContext> video_context;
    ComPtr<ID3D11VideoProcessorEnumerator> enumerator; ComPtr<ID3D11VideoProcessor> processor;
    ComPtr<ID3D11Texture2D> latest; std::uint64_t latest_id = 0, shown_id = 0;
    mutable std::mutex mutex; std::condition_variable wake; std::thread worker; bool stopping=false, visible=true, resize_pending=true;
    RendererStats stats; std::chrono::steady_clock::time_point rate_mark{}; std::uint64_t rate_frames=0;

    HRESULT make_swap() {
        ComPtr<IDXGIDevice> dxgi_device; ComPtr<IDXGIAdapter> adapter; ComPtr<IDXGIFactory2> factory;
        HRESULT hr = device.As(&dxgi_device); if (FAILED(hr)) return hr;
        if (FAILED(hr = dxgi_device->GetAdapter(&adapter)) || FAILED(hr = adapter->GetParent(IID_PPV_ARGS(&factory)))) return hr;
        DXGI_SWAP_CHAIN_DESC1 desc{}; desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM; desc.SampleDesc.Count=1;
        desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT; desc.BufferCount=2; desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
        desc.Scaling=DXGI_SCALING_STRETCH; desc.AlphaMode=DXGI_ALPHA_MODE_IGNORE;
        return factory->CreateSwapChainForHwnd(device.Get(), hwnd, &desc, nullptr, nullptr, &swap);
    }
    HRESULT render(ID3D11Texture2D* input) {
        RECT client{}; GetClientRect(hwnd, &client); UINT dw=static_cast<UINT>(client.right), dh=static_cast<UINT>(client.bottom);
        if (!dw || !dh || IsIconic(hwnd) || !IsWindowVisible(hwnd)) return S_FALSE;
        if (!swap && FAILED(make_swap())) return E_FAIL;
        DXGI_SWAP_CHAIN_DESC1 current{}; swap->GetDesc1(&current);
        if (resize_pending || current.Width!=dw || current.Height!=dh) { context->ClearState(); HRESULT hr=swap->ResizeBuffers(0,dw,dh,DXGI_FORMAT_UNKNOWN,0); if (FAILED(hr)) { swap.Reset(); return hr; } resize_pending=false; }
        D3D11_TEXTURE2D_DESC in{}; input->GetDesc(&in);
        D3D11_VIDEO_PROCESSOR_CONTENT_DESC content{}; content.InputFrameFormat=D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
        content.InputWidth=in.Width; content.InputHeight=in.Height; content.OutputWidth=dw; content.OutputHeight=dh; content.Usage=D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;
        if (!enumerator || !processor) { if (FAILED(video_device->CreateVideoProcessorEnumerator(&content,&enumerator)) || FAILED(video_device->CreateVideoProcessor(enumerator.Get(),0,&processor))) return E_FAIL; }
        ComPtr<ID3D11Texture2D> back; if (FAILED(swap->GetBuffer(0,IID_PPV_ARGS(&back)))) return E_FAIL;
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC iv{}; iv.ViewDimension=D3D11_VPIV_DIMENSION_TEXTURE2D;
        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ov{}; ov.ViewDimension=D3D11_VPOV_DIMENSION_TEXTURE2D;
        ComPtr<ID3D11VideoProcessorInputView> input_view; ComPtr<ID3D11VideoProcessorOutputView> output_view;
        if (FAILED(video_device->CreateVideoProcessorInputView(input,enumerator.Get(),&iv,&input_view)) || FAILED(video_device->CreateVideoProcessorOutputView(back.Get(),enumerator.Get(),&ov,&output_view))) return E_FAIL;
        RECT src{0,0,static_cast<LONG>(in.Width),static_cast<LONG>(in.Height)}, dst{};
        const double sa=static_cast<double>(in.Width)/in.Height, da=static_cast<double>(dw)/dh;
        if (da>sa) { LONG w=static_cast<LONG>(dh*sa); dst={(static_cast<LONG>(dw)-w)/2,0,(static_cast<LONG>(dw)+w)/2,static_cast<LONG>(dh)}; }
        else { LONG h=static_cast<LONG>(dw/sa); dst={0,(static_cast<LONG>(dh)-h)/2,static_cast<LONG>(dw),(static_cast<LONG>(dh)+h)/2}; }
        video_context->VideoProcessorSetStreamSourceRect(processor.Get(),0,TRUE,&src);
        video_context->VideoProcessorSetStreamDestRect(processor.Get(),0,TRUE,&dst);
        D3D11_VIDEO_PROCESSOR_STREAM stream{}; stream.Enable=TRUE; stream.pInputSurface=input_view.Get();
        HRESULT hr=video_context->VideoProcessorBlt(processor.Get(),output_view.Get(),0,1,&stream);
        if (SUCCEEDED(hr)) hr=swap->Present(0,0); return hr;
    }
    void run() { for (;;) { ComPtr<ID3D11Texture2D> frame; std::uint64_t id=0;
        { std::unique_lock lock(mutex); wake.wait(lock,[&]{return stopping || (visible && latest && (latest_id!=shown_id || resize_pending));}); if(stopping)return; frame=latest; id=latest_id; }
        if(frame && SUCCEEDED(render(frame.Get()))) { std::lock_guard lock(mutex); shown_id=id; ++stats.frames_presented; ++rate_frames;
            auto now=std::chrono::steady_clock::now(); if(rate_mark.time_since_epoch().count()==0)rate_mark=now; double s=std::chrono::duration<double>(now-rate_mark).count(); if(s>=.5){stats.render_fps=rate_frames/s;rate_frames=0;rate_mark=now;} }
        else std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }}
};
Renderer::Renderer():state_(std::make_unique<State>()){} Renderer::~Renderer(){shutdown();}
int32_t Renderer::initialize(HWND hwnd, ID3D11Device* device){shutdown();if(!hwnd||!device)return E_INVALIDARG;state_->hwnd=hwnd;state_->device=device;device->GetImmediateContext(&state_->context);HRESULT hr=device->QueryInterface(IID_PPV_ARGS(&state_->video_device));if(FAILED(hr))return hr;if(FAILED(hr=state_->context.As(&state_->video_context)))return hr;state_->stopping=false;state_->worker=std::thread([this]{state_->run();});return 0;}
int32_t Renderer::submit(ID3D11Texture2D* texture,std::uint64_t id){if(!texture)return E_INVALIDARG;std::lock_guard lock(state_->mutex);if(state_->latest_id!=state_->shown_id)++state_->stats.frames_replaced;state_->latest=texture;state_->latest_id=id;state_->wake.notify_one();return 0;}
int32_t Renderer::resize(){std::lock_guard lock(state_->mutex);state_->resize_pending=true;state_->enumerator.Reset();state_->processor.Reset();state_->wake.notify_one();return 0;}
int32_t Renderer::set_visible(bool v){std::lock_guard lock(state_->mutex);state_->visible=v;if(v)state_->wake.notify_one();return 0;}
int32_t Renderer::get_stats(RendererStats& s)const{std::lock_guard lock(state_->mutex);s=state_->stats;return 0;}
int32_t Renderer::shutdown(){{std::lock_guard lock(state_->mutex);state_->stopping=true;}state_->wake.notify_all();if(state_->worker.joinable())state_->worker.join();state_->latest.Reset();state_->swap.Reset();state_->processor.Reset();state_->enumerator.Reset();state_->video_context.Reset();state_->video_device.Reset();state_->context.Reset();state_->device.Reset();return 0;}
} // namespace snowlink
