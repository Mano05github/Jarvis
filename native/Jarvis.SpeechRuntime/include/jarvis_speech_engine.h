#ifndef JARVIS_SPEECH_ENGINE_H
#define JARVIS_SPEECH_ENGINE_H

#include "jarvis_speech_memory.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define JARVIS_SPEECH_ENGINE_ABI_VERSION 1u
#define JARVIS_SPEECH_LANGUAGE_CAPACITY 16u

typedef enum JarvisSpeechEngineStatus {
    JARVIS_SPEECH_ENGINE_OK = 0,
    JARVIS_SPEECH_ENGINE_BUFFER_TOO_SMALL = 1,
    JARVIS_SPEECH_ENGINE_MEMORY_LIMIT = 2,
    JARVIS_SPEECH_ENGINE_CANCELLED = 3,
    JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT = -1,
    JARVIS_SPEECH_ENGINE_INVALID_STATE = -2,
    JARVIS_SPEECH_ENGINE_ABI_MISMATCH = -3,
    JARVIS_SPEECH_ENGINE_BACKEND_ERROR = -4,
    JARVIS_SPEECH_ENGINE_OUTPUT_LIMIT = -5
} JarvisSpeechEngineStatus;

typedef enum JarvisSpeechEngineState {
    JARVIS_SPEECH_ENGINE_UNINITIALIZED = 0,
    JARVIS_SPEECH_ENGINE_READY,
    JARVIS_SPEECH_ENGINE_LISTENING,
    JARVIS_SPEECH_ENGINE_FINISHED,
    JARVIS_SPEECH_ENGINE_CANCELLED_STATE,
    JARVIS_SPEECH_ENGINE_FAULTED,
    JARVIS_SPEECH_ENGINE_DESTROYED
} JarvisSpeechEngineState;

typedef enum JarvisSpeechEngineCapability {
    JARVIS_SPEECH_CAP_STREAMING = 1u << 0,
    JARVIS_SPEECH_CAP_PARTIAL_RESULTS = 1u << 1,
    JARVIS_SPEECH_CAP_CONFIDENCE = 1u << 2,
    JARVIS_SPEECH_CAP_LANGUAGE_ID = 1u << 3,
    JARVIS_SPEECH_CAP_RESET = 1u << 4
} JarvisSpeechEngineCapability;

typedef enum JarvisSpeechResultFlag {
    JARVIS_SPEECH_RESULT_PARTIAL = 1u << 0,
    JARVIS_SPEECH_RESULT_FINAL = 1u << 1
} JarvisSpeechResultFlag;

typedef struct JarvisSpeechAudioFormat {
    uint32_t sample_rate_hz;
    uint16_t channel_count;
    uint16_t bits_per_sample;
} JarvisSpeechAudioFormat;

typedef struct JarvisSpeechEngineConfig {
    uint32_t abi_version;
    uint32_t struct_size;
    JarvisSpeechAudioFormat audio_format;
    uint32_t minimum_chunk_frames;
    uint32_t maximum_chunk_frames;
    uint64_t maximum_result_bytes;
    JarvisSpeechChunkCost chunk_cost;
    JarvisSpeechMemoryBudget *memory_budget;
} JarvisSpeechEngineConfig;

typedef struct JarvisSpeechBackendResultView {
    const char *text;
    uint64_t text_bytes;
    float confidence;
    uint32_t flags;
    char language[JARVIS_SPEECH_LANGUAGE_CAPACITY];
} JarvisSpeechBackendResultView;

typedef int (*JarvisSpeechBackendOpen)(
    void *backend_context,
    const JarvisSpeechEngineConfig *config);
typedef int (*JarvisSpeechBackendSimpleCall)(void *backend_context);
typedef int (*JarvisSpeechBackendAcceptAudio)(
    void *backend_context,
    const int16_t *samples,
    uint32_t frames,
    JarvisSpeechBackendResultView *result);
typedef int (*JarvisSpeechBackendFinish)(
    void *backend_context,
    JarvisSpeechBackendResultView *result);

typedef struct JarvisSpeechBackendOps {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t capabilities;
    uint32_t reserved;
    JarvisSpeechBackendOpen open;
    JarvisSpeechBackendSimpleCall start;
    JarvisSpeechBackendAcceptAudio accept_audio;
    JarvisSpeechBackendFinish finish;
    JarvisSpeechBackendSimpleCall cancel;
    JarvisSpeechBackendSimpleCall reset;
    JarvisSpeechBackendSimpleCall close;
} JarvisSpeechBackendOps;

typedef struct JarvisSpeechResult {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t flags;
    uint32_t accepted_frames;
    float confidence;
    uint32_t reserved;
    char *text;
    uint64_t text_capacity;
    uint64_t text_bytes;
    uint64_t required_text_capacity;
    char language[JARVIS_SPEECH_LANGUAGE_CAPACITY];
} JarvisSpeechResult;

typedef struct JarvisSpeechEngine {
    uint32_t abi_version;
    uint32_t struct_size;
    JarvisSpeechEngineState state;
    uint32_t reserved;
    JarvisSpeechEngineConfig config;
    const JarvisSpeechBackendOps *backend_ops;
    void *backend_context;
} JarvisSpeechEngine;

int jarvis_speech_engine_init(
    JarvisSpeechEngine *engine,
    const JarvisSpeechEngineConfig *config,
    const JarvisSpeechBackendOps *backend_ops,
    void *backend_context);
int jarvis_speech_engine_start(JarvisSpeechEngine *engine);
int jarvis_speech_engine_accept_audio(
    JarvisSpeechEngine *engine,
    const int16_t *samples,
    uint32_t frames,
    JarvisSpeechResult *result);
int jarvis_speech_engine_finish(
    JarvisSpeechEngine *engine,
    JarvisSpeechResult *result);
int jarvis_speech_engine_cancel(JarvisSpeechEngine *engine);
int jarvis_speech_engine_reset(JarvisSpeechEngine *engine);
int jarvis_speech_engine_destroy(JarvisSpeechEngine *engine);

const char *jarvis_speech_engine_status_name(int status);
const char *jarvis_speech_engine_state_name(JarvisSpeechEngineState state);

#ifdef __cplusplus
}
#endif

#endif
