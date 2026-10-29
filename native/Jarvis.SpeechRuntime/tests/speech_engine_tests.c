#include "jarvis_speech_engine.h"

#include <stdio.h>
#include <string.h>

typedef struct FakeBackend {
    int open_calls;
    int start_calls;
    int accept_calls;
    int finish_calls;
    int cancel_calls;
    int reset_calls;
    int close_calls;
    int fail_open;
    int fail_accept;
    int oversized_output;
    uint32_t last_frames;
} FakeBackend;

static int failures = 0;
static int checks = 0;

#define CHECK(condition)                                                        \
    do {                                                                        \
        ++checks;                                                               \
        if (!(condition)) {                                                     \
            ++failures;                                                         \
            fprintf(stderr, "check failed at %s:%d: %s\n", __FILE__, __LINE__, \
                    #condition);                                                \
        }                                                                       \
    } while (0)

static void set_view(
    JarvisSpeechBackendResultView *result,
    const char *text,
    uint32_t flags) {
    memset(result, 0, sizeof(*result));
    result->text = text;
    result->text_bytes = (uint64_t)strlen(text);
    result->confidence = 0.875f;
    result->flags = flags;
    memcpy(result->language, "ta-en", 6u);
}

static int fake_open(
    void *backend_context,
    const JarvisSpeechEngineConfig *config) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    (void)config;
    ++backend->open_calls;
    return backend->fail_open ? -1 : 0;
}

static int fake_start(void *backend_context) {
    ++((FakeBackend *)backend_context)->start_calls;
    return 0;
}

static int fake_accept(
    void *backend_context,
    const int16_t *samples,
    uint32_t frames,
    JarvisSpeechBackendResultView *result) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    (void)samples;
    ++backend->accept_calls;
    backend->last_frames = frames;
    if (backend->fail_accept) {
        return -1;
    }
    set_view(result, "calculator", JARVIS_SPEECH_RESULT_PARTIAL);
    if (backend->oversized_output) {
        result->text_bytes = 1000u;
    }
    return 0;
}

static int fake_finish(
    void *backend_context,
    JarvisSpeechBackendResultView *result) {
    ++((FakeBackend *)backend_context)->finish_calls;
    set_view(result, "calculator open pannu", JARVIS_SPEECH_RESULT_FINAL);
    return 0;
}

static int fake_cancel(void *backend_context) {
    ++((FakeBackend *)backend_context)->cancel_calls;
    return 0;
}

static int fake_reset(void *backend_context) {
    ++((FakeBackend *)backend_context)->reset_calls;
    return 0;
}

static int fake_close(void *backend_context) {
    ++((FakeBackend *)backend_context)->close_calls;
    return 0;
}

static JarvisSpeechBackendOps make_ops(void) {
    JarvisSpeechBackendOps ops;
    memset(&ops, 0, sizeof(ops));
    ops.abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    ops.struct_size = (uint32_t)sizeof(ops);
    ops.capabilities = JARVIS_SPEECH_CAP_STREAMING |
                       JARVIS_SPEECH_CAP_PARTIAL_RESULTS |
                       JARVIS_SPEECH_CAP_CONFIDENCE |
                       JARVIS_SPEECH_CAP_LANGUAGE_ID |
                       JARVIS_SPEECH_CAP_RESET;
    ops.open = fake_open;
    ops.start = fake_start;
    ops.accept_audio = fake_accept;
    ops.finish = fake_finish;
    ops.cancel = fake_cancel;
    ops.reset = fake_reset;
    ops.close = fake_close;
    return ops;
}

static JarvisSpeechEngineConfig make_config(JarvisSpeechMemoryBudget *budget) {
    JarvisSpeechEngineConfig config;
    memset(&config, 0, sizeof(config));
    config.abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    config.struct_size = (uint32_t)sizeof(config);
    config.audio_format.sample_rate_hz = 16000u;
    config.audio_format.channel_count = 1u;
    config.audio_format.bits_per_sample = 16u;
    config.minimum_chunk_frames = 4u;
    config.maximum_chunk_frames = 20u;
    config.maximum_result_bytes = 64u;
    config.chunk_cost.fixed_private_bytes = 100u;
    config.chunk_cost.fixed_physical_bytes = 100u;
    config.chunk_cost.private_bytes_per_frame = 10u;
    config.chunk_cost.physical_bytes_per_frame = 10u;
    config.memory_budget = budget;
    return config;
}

static JarvisSpeechResult make_result(char *text, uint64_t capacity) {
    JarvisSpeechResult result;
    memset(&result, 0, sizeof(result));
    result.abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    result.struct_size = (uint32_t)sizeof(result);
    result.text = text;
    result.text_capacity = capacity;
    return result;
}

static void test_lifecycle_and_adaptive_chunk(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechEngineConfig config;
    JarvisSpeechBackendOps ops = make_ops();
    JarvisSpeechEngine engine;
    JarvisSpeechResult result;
    FakeBackend backend;
    int16_t samples[20] = {0};
    char text[64];
    memset(&backend, 0, sizeof(backend));
    jarvis_speech_memory_init(&budget, 500u, 500u);
    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_PERMANENT, 300u, 300u) == 0);
    config = make_config(&budget);
    result = make_result(text, sizeof(text));

    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_READY && backend.open_calls == 1);
    CHECK(jarvis_speech_engine_start(&engine) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_LISTENING);
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 20u, &result) == 0);
    CHECK(backend.accept_calls == 1 && backend.last_frames == 10u);
    CHECK(result.accepted_frames == 10u &&
          result.flags == JARVIS_SPEECH_RESULT_PARTIAL);
    CHECK(strcmp(result.text, "calculator") == 0);
    CHECK(strcmp(result.language, "ta-en") == 0 && result.confidence > 0.8f);
    CHECK(budget.current_private_bytes == 300u &&
          budget.current_physical_bytes == 300u);
    CHECK(budget.peak_private_by_phase[JARVIS_SPEECH_PHASE_ENCODE] == 500u);
    CHECK(jarvis_speech_engine_finish(&engine, &result) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_FINISHED &&
          strcmp(result.text, "calculator open pannu") == 0);
    CHECK(result.flags == JARVIS_SPEECH_RESULT_FINAL && backend.finish_calls == 1);
    CHECK(jarvis_speech_engine_start(&engine) ==
          JARVIS_SPEECH_ENGINE_INVALID_STATE);
    CHECK(jarvis_speech_engine_reset(&engine) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_READY && backend.reset_calls == 1);
    CHECK(jarvis_speech_engine_destroy(&engine) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_DESTROYED &&
          backend.close_calls == 1);
}

static void test_memory_denial_never_calls_backend(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechEngineConfig config;
    JarvisSpeechBackendOps ops = make_ops();
    JarvisSpeechEngine engine;
    JarvisSpeechResult result;
    FakeBackend backend;
    int16_t samples[20] = {0};
    char text[64];
    memset(&backend, 0, sizeof(backend));
    jarvis_speech_memory_init(&budget, 350u, 350u);
    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_PERMANENT, 300u, 300u) == 0);
    config = make_config(&budget);
    result = make_result(text, sizeof(text));
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) == 0);
    CHECK(jarvis_speech_engine_start(&engine) == 0);
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 20u, &result) ==
          JARVIS_SPEECH_ENGINE_MEMORY_LIMIT);
    CHECK(backend.accept_calls == 0 && budget.current_private_bytes == 300u);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_LISTENING);
    CHECK(jarvis_speech_engine_destroy(&engine) == 0);
}

static void test_cancellation_and_reset(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechEngineConfig config;
    JarvisSpeechBackendOps ops = make_ops();
    JarvisSpeechEngine engine;
    JarvisSpeechResult result;
    FakeBackend backend;
    int16_t samples[4] = {0};
    char text[64];
    memset(&backend, 0, sizeof(backend));
    jarvis_speech_memory_init(&budget, 1000u, 1000u);
    config = make_config(&budget);
    result = make_result(text, sizeof(text));
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) == 0);
    CHECK(jarvis_speech_engine_cancel(&engine) == 0);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_CANCELLED_STATE &&
          backend.cancel_calls == 1);
    CHECK(jarvis_speech_engine_cancel(&engine) ==
          JARVIS_SPEECH_ENGINE_CANCELLED);
    CHECK(backend.cancel_calls == 1);
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 4u, &result) == JARVIS_SPEECH_ENGINE_CANCELLED);
    CHECK(backend.accept_calls == 0);
    CHECK(jarvis_speech_engine_reset(&engine) == 0);
    CHECK(jarvis_speech_engine_start(&engine) == 0);
    CHECK(jarvis_speech_engine_cancel(&engine) == 0);
    CHECK(backend.cancel_calls == 2);
    CHECK(jarvis_speech_engine_destroy(&engine) == 0);
}

static void test_bounded_output_and_backend_failure(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechEngineConfig config;
    JarvisSpeechBackendOps ops = make_ops();
    JarvisSpeechEngine engine;
    JarvisSpeechResult result;
    FakeBackend backend;
    int16_t samples[4] = {0};
    char tiny_text[4];
    char text[64];
    memset(&backend, 0, sizeof(backend));
    jarvis_speech_memory_init(&budget, 1000u, 1000u);
    config = make_config(&budget);
    result = make_result(tiny_text, sizeof(tiny_text));
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) == 0);
    CHECK(jarvis_speech_engine_start(&engine) == 0);
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 4u, &result) ==
          JARVIS_SPEECH_ENGINE_BUFFER_TOO_SMALL);
    CHECK(result.required_text_capacity == 11u && result.accepted_frames == 4u);
    CHECK(tiny_text[0] == '\0' && engine.state == JARVIS_SPEECH_ENGINE_LISTENING);

    backend.fail_accept = 1;
    result = make_result(text, sizeof(text));
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 4u, &result) ==
          JARVIS_SPEECH_ENGINE_BACKEND_ERROR);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_FAULTED);
    CHECK(budget.current_private_bytes == 0u && budget.current_physical_bytes == 0u);
    CHECK(jarvis_speech_engine_reset(&engine) == 0);
    backend.fail_accept = 0;
    backend.oversized_output = 1;
    CHECK(jarvis_speech_engine_start(&engine) == 0);
    CHECK(jarvis_speech_engine_accept_audio(
              &engine, samples, 4u, &result) ==
          JARVIS_SPEECH_ENGINE_OUTPUT_LIMIT);
    CHECK(engine.state == JARVIS_SPEECH_ENGINE_FAULTED);
    CHECK(jarvis_speech_engine_destroy(&engine) == 0);
}

static void test_validation_and_names(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechEngineConfig config;
    JarvisSpeechBackendOps ops = make_ops();
    JarvisSpeechEngine engine;
    FakeBackend backend;
    memset(&backend, 0, sizeof(backend));
    jarvis_speech_memory_init(&budget, 1000u, 1000u);
    config = make_config(&budget);

    config.abi_version = 99u;
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) ==
          JARVIS_SPEECH_ENGINE_ABI_MISMATCH);
    CHECK(backend.open_calls == 0);
    config = make_config(&budget);
    config.audio_format.sample_rate_hz = 48000u;
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) ==
          JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT);
    CHECK(backend.open_calls == 0);
    config = make_config(&budget);
    ops.capabilities = 0u;
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) ==
          JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT);
    ops = make_ops();
    backend.fail_open = 1;
    CHECK(jarvis_speech_engine_init(&engine, &config, &ops, &backend) ==
          JARVIS_SPEECH_ENGINE_BACKEND_ERROR);
    CHECK(backend.open_calls == 1 && backend.close_calls == 1);
    CHECK(jarvis_speech_engine_destroy(&engine) ==
          JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT);
    CHECK(strcmp(jarvis_speech_engine_status_name(
                     JARVIS_SPEECH_ENGINE_MEMORY_LIMIT),
                 "memory-limit") == 0);
    CHECK(strcmp(jarvis_speech_engine_state_name(JARVIS_SPEECH_ENGINE_READY),
                 "ready") == 0);
    CHECK(strcmp(jarvis_speech_engine_state_name((JarvisSpeechEngineState)99),
                 "invalid") == 0);
}

int main(void) {
    test_lifecycle_and_adaptive_chunk();
    test_memory_denial_never_calls_backend();
    test_cancellation_and_reset();
    test_bounded_output_and_backend_failure();
    test_validation_and_names();
    if (failures != 0) {
        fprintf(stderr, "Speech engine contract failed: %d/%d checks\n",
                failures, checks);
        return 1;
    }
    printf("Speech engine contract passed: %d checks\n", checks);
    return 0;
}
