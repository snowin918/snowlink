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
