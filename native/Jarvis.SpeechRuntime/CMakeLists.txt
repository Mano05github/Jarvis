cmake_minimum_required(VERSION 3.20)
project(JarvisSpeechRuntime VERSION 0.1.0 LANGUAGES C)

add_library(jarvis_speech_memory STATIC
    src/jarvis_speech_memory.c
)
target_include_directories(jarvis_speech_memory PUBLIC include)
target_compile_features(jarvis_speech_memory PUBLIC c_std_11)

if(MSVC)
    target_compile_options(jarvis_speech_memory PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_memory PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(jarvis_speech_engine STATIC
    src/jarvis_speech_engine.c
)
target_include_directories(jarvis_speech_engine PUBLIC include)
target_compile_features(jarvis_speech_engine PUBLIC c_std_11)
target_link_libraries(jarvis_speech_engine PUBLIC jarvis_speech_memory)
if(MSVC)
    target_compile_options(jarvis_speech_engine PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_engine PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(jarvis_speech_protocol STATIC
    src/jarvis_speech_protocol.c
)
target_include_directories(jarvis_speech_protocol PUBLIC include)
target_compile_features(jarvis_speech_protocol PUBLIC c_std_11)
if(MSVC)
    target_compile_options(jarvis_speech_protocol PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

if(WIN32)
    add_executable(jarvis_speech_fake_worker
        src/jarvis_speech_fake_worker.c
    )
    target_link_libraries(jarvis_speech_fake_worker PRIVATE
        jarvis_speech_engine
        jarvis_speech_protocol
        bcrypt
    )
    target_compile_features(jarvis_speech_fake_worker PRIVATE c_std_11)
    target_compile_definitions(jarvis_speech_fake_worker PRIVATE
        JARVIS_SPEECH_ENABLE_TEST_HOOKS=1
    )
    if(MSVC)
        target_compile_options(jarvis_speech_fake_worker PRIVATE /W4 /WX)
    else()
        target_compile_options(jarvis_speech_fake_worker PRIVATE
            -Wall -Wextra -Wpedantic -Werror)
    endif()
endif()

add_executable(jarvis_speech_memory_tests
    tests/speech_memory_tests.c
)
target_link_libraries(jarvis_speech_memory_tests PRIVATE jarvis_speech_memory)
if(MSVC)
    target_compile_options(jarvis_speech_memory_tests PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_memory_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(jarvis_speech_engine_tests
    tests/speech_engine_tests.c
)
target_link_libraries(jarvis_speech_engine_tests PRIVATE jarvis_speech_engine)
if(MSVC)
    target_compile_options(jarvis_speech_engine_tests PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_engine_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(jarvis_speech_protocol_tests
    tests/speech_protocol_tests.c
)
target_link_libraries(jarvis_speech_protocol_tests PRIVATE jarvis_speech_protocol)
if(MSVC)
    target_compile_options(jarvis_speech_protocol_tests PRIVATE /W4 /WX)
else()
    target_compile_options(jarvis_speech_protocol_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

set(JARVIS_ONNXRUNTIME_ROOT "" CACHE PATH "Pinned ONNX Runtime root")
set(JARVIS_ONNX_FIXTURE_MODEL "" CACHE FILEPATH "Verified tiny ONNX fixture")
if(JARVIS_ONNXRUNTIME_ROOT OR JARVIS_ONNX_FIXTURE_MODEL)
    if(NOT WIN32)
        message(FATAL_ERROR "The pinned ONNX fixture gate currently requires Windows x64")
    endif()
    if(NOT EXISTS "${JARVIS_ONNXRUNTIME_ROOT}/include/onnxruntime_c_api.h")
        message(FATAL_ERROR "Pinned ONNX Runtime header is missing")
    endif()
    if(NOT EXISTS "${JARVIS_ONNXRUNTIME_ROOT}/lib/onnxruntime.lib")
        message(FATAL_ERROR "Pinned ONNX Runtime import library is missing")
    endif()
    if(NOT EXISTS "${JARVIS_ONNXRUNTIME_ROOT}/lib/onnxruntime.dll")
        message(FATAL_ERROR "Pinned ONNX Runtime DLL is missing")
    endif()
    if(NOT EXISTS "${JARVIS_ONNX_FIXTURE_MODEL}")
        message(FATAL_ERROR "Verified tiny ONNX fixture is missing")
    endif()

    add_library(jarvis_pinned_onnxruntime SHARED IMPORTED)
    set_target_properties(jarvis_pinned_onnxruntime PROPERTIES
        IMPORTED_IMPLIB "${JARVIS_ONNXRUNTIME_ROOT}/lib/onnxruntime.lib"
        IMPORTED_LOCATION "${JARVIS_ONNXRUNTIME_ROOT}/lib/onnxruntime.dll"
        INTERFACE_INCLUDE_DIRECTORIES "${JARVIS_ONNXRUNTIME_ROOT}/include"
    )

    add_library(jarvis_speech_onnx_fixture STATIC
        src/jarvis_speech_onnx_fixture.c
    )
    target_include_directories(jarvis_speech_onnx_fixture PUBLIC include)
    target_compile_features(jarvis_speech_onnx_fixture PUBLIC c_std_11)
    target_link_libraries(jarvis_speech_onnx_fixture PUBLIC
        jarvis_pinned_onnxruntime)
    if(MSVC)
        target_compile_options(jarvis_speech_onnx_fixture PRIVATE /W4 /WX)
    else()
        target_compile_options(jarvis_speech_onnx_fixture PRIVATE
            -Wall -Wextra -Wpedantic -Werror)
    endif()

    add_executable(jarvis_speech_onnx_fixture_tests
        tests/speech_onnx_fixture_tests.c
    )
    target_link_libraries(jarvis_speech_onnx_fixture_tests PRIVATE
        jarvis_speech_onnx_fixture)
    if(MSVC)
        target_compile_options(jarvis_speech_onnx_fixture_tests PRIVATE /W4 /WX)
    else()
        target_compile_options(jarvis_speech_onnx_fixture_tests PRIVATE
            -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_custom_command(TARGET jarvis_speech_onnx_fixture_tests POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${JARVIS_ONNXRUNTIME_ROOT}/lib/onnxruntime.dll"
            "$<TARGET_FILE_DIR:jarvis_speech_onnx_fixture_tests>"
    )
endif()

enable_testing()
add_test(NAME jarvis_speech_memory_contract COMMAND jarvis_speech_memory_tests)
add_test(NAME jarvis_speech_engine_contract COMMAND jarvis_speech_engine_tests)
add_test(NAME jarvis_speech_protocol_contract COMMAND jarvis_speech_protocol_tests)
if(TARGET jarvis_speech_onnx_fixture_tests)
    add_test(
        NAME jarvis_speech_onnx_fixture_contract
        COMMAND jarvis_speech_onnx_fixture_tests "${JARVIS_ONNX_FIXTURE_MODEL}"
    )
endif()
