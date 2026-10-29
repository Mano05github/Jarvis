#ifndef JARVIS_SPEECH_ONNX_FIXTURE_H
#define JARVIS_SPEECH_ONNX_FIXTURE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define JARVIS_SPEECH_ONNX_FIXTURE_ABI_VERSION 1u
#define JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT 4u
#define JARVIS_SPEECH_ONNX_FIXTURE_ERROR_CAPACITY 256u

typedef enum JarvisSpeechOnnxFixtureStatus {
    JARVIS_SPEECH_ONNX_FIXTURE_OK = 0,
    JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT = -1,
    JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE = -2,
    JARVIS_SPEECH_ONNX_FIXTURE_API_UNAVAILABLE = -3,
    JARVIS_SPEECH_ONNX_FIXTURE_RUNTIME_ERROR = -4,
    JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID = -5
} JarvisSpeechOnnxFixtureStatus;

typedef enum JarvisSpeechOnnxFixtureState {
    JARVIS_SPEECH_ONNX_FIXTURE_UNINITIALIZED = 0,
    JARVIS_SPEECH_ONNX_FIXTURE_READY,
    JARVIS_SPEECH_ONNX_FIXTURE_FAULTED,
    JARVIS_SPEECH_ONNX_FIXTURE_DESTROYED
} JarvisSpeechOnnxFixtureState;

typedef struct JarvisSpeechOnnxFixture {
    uint32_t abi_version;
    uint32_t struct_size;
    JarvisSpeechOnnxFixtureState state;
    uint32_t reserved;
    const void *api;
    void *environment;
    void *session;
    void *memory_info;
    char last_error[JARVIS_SPEECH_ONNX_FIXTURE_ERROR_CAPACITY];
} JarvisSpeechOnnxFixture;

int jarvis_speech_onnx_fixture_init(
    JarvisSpeechOnnxFixture *fixture,
    const void *model_data,
    size_t model_bytes);
int jarvis_speech_onnx_fixture_run(
    JarvisSpeechOnnxFixture *fixture,
    const float input[JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT],
    float output[JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT]);
int jarvis_speech_onnx_fixture_destroy(JarvisSpeechOnnxFixture *fixture);

const char *jarvis_speech_onnx_fixture_last_error(
    const JarvisSpeechOnnxFixture *fixture);
const char *jarvis_speech_onnx_fixture_status_name(int status);

#ifdef __cplusplus
}
#endif

#endif
