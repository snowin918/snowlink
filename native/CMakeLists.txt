cmake_minimum_required(VERSION 3.21)
project(snowlink_engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(snowlink_engine SHARED
    src/engine.cpp
    src/c_api.cpp
    src/capture/capture_manager.cpp
    src/encode/encoder.cpp
    src/decode/decoder.cpp
    src/render/renderer.cpp
    src/transport/transport.cpp
    src/cursor/cursor.cpp
    src/input/input.cpp
    src/capture/wgc_capture_backend.cpp
    src/capture/dxgi_capture_backend.cpp
    src/process/gpu_frame_processor.cpp
)

target_include_directories(snowlink_engine
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src/common>
        $<INSTALL_INTERFACE:include>
)

target_compile_definitions(snowlink_engine PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)

target_link_libraries(snowlink_engine
    PRIVATE
        d3d11
        dxgi
        windowsapp
        mfplat
        mfuuid
)

if (MSVC)
    target_compile_options(snowlink_engine PRIVATE /W4 /permissive-)
endif()

set_target_properties(snowlink_engine PROPERTIES
    OUTPUT_NAME snowlink_engine
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin
)

option(SNOWLINK_BUILD_CAPTURE_TEST "Build the GPU-only native capture development test" ON)
if (SNOWLINK_BUILD_CAPTURE_TEST)
    add_executable(snowlink_capture_test
        tools/capture_test.cpp
        src/capture/capture_manager.cpp
        src/capture/wgc_capture_backend.cpp
        src/capture/dxgi_capture_backend.cpp)
    target_sources(snowlink_capture_test PRIVATE src/process/gpu_frame_processor.cpp)
    target_include_directories(snowlink_capture_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_compile_definitions(snowlink_capture_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(snowlink_capture_test PRIVATE d3d11 dxgi windowsapp)
    set_target_properties(snowlink_capture_test PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin)
    if (MSVC)
        target_compile_options(snowlink_capture_test PRIVATE /W4 /permissive-)
    endif()
endif()
