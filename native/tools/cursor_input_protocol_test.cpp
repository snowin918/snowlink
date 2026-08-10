#include "snowlink/cursor.h"
#include "snowlink/input.h"
#include <cassert>
#include <iostream>
int main(){
 snowlink::CursorState s;s.x=-17;s.y=901;s.visible=true;s.shape_id=42;s.hotspot_x=3;s.hotspot_y=7;s.timestamp=99;
 auto state=snowlink::encode_cursor_state(s);snowlink::CursorState decoded; snowlink::CursorShape unused;assert(snowlink::decode_cursor_message(state.data(),state.size(),&decoded,&unused));assert(decoded.x==-17&&decoded.shape_id==42&&decoded.hotspot_y==7);
 snowlink::CursorShape shape;shape.shape_id=55;shape.width=2;shape.height=2;shape.hotspot_x=1;shape.pixels.assign(16,0x7f);auto bytes=snowlink::encode_cursor_shape(shape);snowlink::CursorShape shape2;assert(snowlink::decode_cursor_message(bytes.data(),bytes.size(),&decoded,&shape2));assert(shape2.pixels==shape.pixels&&shape2.shape_id==55);bytes.pop_back();assert(!snowlink::decode_cursor_message(bytes.data(),bytes.size(),&decoded,&shape2));
 snowlink::RemoteInputEvent input;input.kind=snowlink::InputKind::MouseButton;input.code=2;input.down=true;input.sequence=123;auto wire=snowlink::encode_input_event(input);snowlink::RemoteInputEvent input2;assert(snowlink::decode_input_event(wire.data(),wire.size(),input2));assert(input2.code==2&&input2.down&&input2.sequence==123);wire[0]=9;assert(!snowlink::decode_input_event(wire.data(),wire.size(),input2));
 std::cout<<"cursor/input protocol tests passed\n";
}
