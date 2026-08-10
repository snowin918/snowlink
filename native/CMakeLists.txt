cmake_minimum_required(VERSION 3.21)
project(snowlink_engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
set(NO_EXAMPLES ON CACHE BOOL "" FORCE)
set(NO_TESTS ON CACHE BOOL "" FORCE)
set(NO_WEBSOCKET ON CACHE BOOL "" FORCE)
set(NO_MEDIA OFF CACHE BOOL "" FORCE)
set(USE_MBEDTLS OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
find_package(OpenSSL 1.1 REQUIRED)
FetchContent_Declare(libdatachannel
    GIT_REPOSITORY https://github.com/paullouisageneau/libdatachannel.git
    GIT_TAG c6696d157b5612df2a741d9a03b192b47ab6cefb
    GIT_SHALLOW TRUE
    GIT_SUBMODULES_RECURSE TRUE)
FetchContent_MakeAvailable(libdatachannel)

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
        mf
        mfreadwrite
        mfuuid
        oleaut32
        user32
        gdi32
        LibDataChannel::LibDataChannelStatic
)

if (MSVC)
    target_compile_options(snowlink_engine PRIVATE /W4 /permissive-)
endif()

set_target_properties(snowlink_engine PROPERTIES
    OUTPUT_NAME snowlink_engine
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin
)

# FindOpenSSL supplies import libraries on Windows; bundle their corresponding
# runtime DLLs beside snowlink_engine.dll so ctypes uses the secure default DLL
# search path and packaging does not depend on a machine-wide PATH entry.
if (WIN32 AND OPENSSL_CRYPTO_LIBRARY)
    get_filename_component(_snowlink_openssl_lib_dir "${OPENSSL_CRYPTO_LIBRARY}" DIRECTORY)
    get_filename_component(_snowlink_openssl_root "${_snowlink_openssl_lib_dir}" DIRECTORY)
    find_file(SNOWLINK_OPENSSL_CRYPTO_DLL NAMES libcrypto-3-x64.dll libcrypto-3.dll
        HINTS "${_snowlink_openssl_root}/bin" NO_DEFAULT_PATH)
    find_file(SNOWLINK_OPENSSL_SSL_DLL NAMES libssl-3-x64.dll libssl-3.dll
        HINTS "${_snowlink_openssl_root}/bin" NO_DEFAULT_PATH)
    foreach(_snowlink_runtime IN ITEMS "${SNOWLINK_OPENSSL_CRYPTO_DLL}" "${SNOWLINK_OPENSSL_SSL_DLL}")
        if (EXISTS "${_snowlink_runtime}")
            add_custom_command(TARGET snowlink_engine POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "${_snowlink_runtime}" "$<TARGET_FILE_DIR:snowlink_engine>")
        endif()
    endforeach()
endif()

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

option(SNOWLINK_BUILD_TRANSPORT_TEST "Build native H.264 RTP packet tests" ON)
if (SNOWLINK_BUILD_TRANSPORT_TEST)
    add_executable(snowlink_transport_packet_test tools/transport_packet_test.cpp)
    target_link_libraries(snowlink_transport_packet_test PRIVATE LibDataChannel::LibDataChannelStatic)
    set_target_properties(snowlink_transport_packet_test PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin)
    if (MSVC)
        target_compile_options(snowlink_transport_packet_test PRIVATE /W4 /permissive-)
    endif()
endif()

add_executable(snowlink_cursor_input_protocol_test
    tools/cursor_input_protocol_test.cpp src/cursor/cursor.cpp src/input/input.cpp)
target_include_directories(snowlink_cursor_input_protocol_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_definitions(snowlink_cursor_input_protocol_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(snowlink_cursor_input_protocol_test PRIVATE user32 gdi32)
set_target_properties(snowlink_cursor_input_protocol_test PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin)

option(SNOWLINK_BUILD_ENCODER_BENCHMARK "Build the capture-to-hardware-encode benchmark" ON)
if (SNOWLINK_BUILD_ENCODER_BENCHMARK)
    add_executable(snowlink_encoder_benchmark
        tools/encoder_benchmark.cpp
        src/capture/capture_manager.cpp
        src/capture/wgc_capture_backend.cpp
        src/capture/dxgi_capture_backend.cpp
        src/process/gpu_frame_processor.cpp
        src/encode/encoder.cpp)
    target_include_directories(snowlink_encoder_benchmark PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_compile_definitions(snowlink_encoder_benchmark PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(snowlink_encoder_benchmark PRIVATE d3d11 dxgi windowsapp mf mfplat mfreadwrite mfuuid oleaut32)
    set_target_properties(snowlink_encoder_benchmark PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin)
    if (MSVC)
        target_compile_options(snowlink_encoder_benchmark PRIVATE /W4 /permissive-)
    endif()
endif()
