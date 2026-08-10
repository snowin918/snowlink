#include "snowlink/input.h"
#include <Windows.h>
#include <algorithm>
#include <cstring>

namespace snowlink { namespace {
#pragma pack(push,1)
struct WireInput { std::uint8_t version=1,type=3,kind=0,code=0,down=0,reserved[3]{}; std::int32_t x=0,y=0,delta=0; std::uint64_t sequence=0; };
#pragma pack(pop)
}
InputSubsystem::InputSubsystem()=default; InputSubsystem::~InputSubsystem(){shutdown();}
int32_t InputSubsystem::initialize(){authorized_=false;return 0;}
void InputSubsystem::set_authorized(bool value) noexcept { authorized_=value; }
void InputSubsystem::set_source_desktop(std::int32_t l,std::int32_t t,std::uint32_t w,std::uint32_t h) noexcept {left_=l;top_=t;width_=w;height_=h;}
int32_t InputSubsystem::inject(const RemoteInputEvent& e){
    if(!authorized_) return ERROR_ACCESS_DENIED;
    INPUT in{};
    if(e.kind==InputKind::MouseMove){
        if(!width_||!height_)return E_INVALIDARG;
        const int vx=GetSystemMetrics(SM_XVIRTUALSCREEN),vy=GetSystemMetrics(SM_YVIRTUALSCREEN);
        const int vw=GetSystemMetrics(SM_CXVIRTUALSCREEN),vh=GetSystemMetrics(SM_CYVIRTUALSCREEN);
        const int sx=left_+std::clamp(e.x,0,static_cast<int>(width_-1));
        const int sy=top_+std::clamp(e.y,0,static_cast<int>(height_-1));
        in.type=INPUT_MOUSE;in.mi.dx=MulDiv(sx-vx,65535,std::max(1,vw-1));in.mi.dy=MulDiv(sy-vy,65535,std::max(1,vh-1));
        in.mi.dwFlags=MOUSEEVENTF_MOVE|MOUSEEVENTF_ABSOLUTE|MOUSEEVENTF_VIRTUALDESK;
    } else if(e.kind==InputKind::MouseButton){
        in.type=INPUT_MOUSE; const DWORD down[]={0,MOUSEEVENTF_LEFTDOWN,MOUSEEVENTF_RIGHTDOWN,MOUSEEVENTF_MIDDLEDOWN,MOUSEEVENTF_XDOWN,MOUSEEVENTF_XDOWN};
        const DWORD up[]={0,MOUSEEVENTF_LEFTUP,MOUSEEVENTF_RIGHTUP,MOUSEEVENTF_MIDDLEUP,MOUSEEVENTF_XUP,MOUSEEVENTF_XUP};
        if(e.code<1||e.code>5)return E_INVALIDARG;in.mi.dwFlags=e.down?down[e.code]:up[e.code];if(e.code>=4)in.mi.mouseData=e.code==4?XBUTTON1:XBUTTON2;
    } else if(e.kind==InputKind::Wheel){in.type=INPUT_MOUSE;in.mi.dwFlags=MOUSEEVENTF_WHEEL;in.mi.mouseData=static_cast<DWORD>(e.delta);
    } else if(e.kind==InputKind::Key){in.type=INPUT_KEYBOARD;in.ki.wVk=e.code;in.ki.dwFlags=e.down?0:KEYEVENTF_KEYUP;
    } else return E_INVALIDARG;
    return SendInput(1,&in,sizeof(in))==1?0:static_cast<int32_t>(GetLastError());
}
int32_t InputSubsystem::shutdown(){authorized_=false;return 0;}
std::vector<std::uint8_t> encode_input_event(const RemoteInputEvent&e){WireInput w;w.kind=static_cast<uint8_t>(e.kind);w.code=e.code;w.down=e.down;w.x=e.x;w.y=e.y;w.delta=e.delta;w.sequence=e.sequence;std::vector<uint8_t>b(sizeof w);memcpy(b.data(),&w,sizeof w);return b;}
bool decode_input_event(const uint8_t*d,size_t n,RemoteInputEvent&e){if(!d||n!=sizeof(WireInput))return false;WireInput w;memcpy(&w,d,n);if(w.version!=1||w.type!=3||w.kind<1||w.kind>4)return false;e.kind=static_cast<InputKind>(w.kind);e.code=w.code;e.down=w.down!=0;e.x=w.x;e.y=w.y;e.delta=w.delta;e.sequence=w.sequence;return true;}
} // namespace snowlink
