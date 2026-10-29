#include "jarvis_speech_engine.h"

#include <stddef.h>
#include <string.h>

static int engine_is_live(const JarvisSpeechEngine *engine) {
    return engine != NULL &&
           engine->abi_version == JARVIS_SPEECH_ENGINE_ABI_VERSION &&
           engine->struct_size >= (uint32_t)sizeof(*engine) &&
           engine->backend_ops != NULL;
}

static int validate_result(JarvisSpeechResult *result) {
    if (result == NULL) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (result->abi_version != JARVIS_SPEECH_ENGINE_ABI_VERSION ||
        result->struct_size < (uint32_t)sizeof(*result)) {
        return JARVIS_SPEECH_ENGINE_ABI_MISMATCH;
    }
    if (result->text == NULL || result->text_capacity == 0u) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (result->text_capacity > (uint64_t)SIZE_MAX) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    result->flags = 0u;
    result->accepted_frames = 0u;
    result->confidence = 0.0f;
    result->text_bytes = 0u;
    result->required_text_capacity = 1u;
    result->text[0] = '\0';
    memset(result->language, 0, sizeof(result->language));
    return JARVIS_SPEECH_ENGINE_OK;
}

static int publish_result(
    JarvisSpeechEngine *engine,
    const JarvisSpeechBackendResultView *view,
    uint32_t accepted_frames,
    int final_result,
    JarvisSpeechResult *result) {
    uint64_t required;
    size_t language_length;
    if (view == NULL || (view->text == NULL && view->text_bytes != 0u)) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    if ((view->flags & ~(JARVIS_SPEECH_RESULT_PARTIAL |
                         JARVIS_SPEECH_RESULT_FINAL)) != 0u ||
        (final_result && view->flags != JARVIS_SPEECH_RESULT_FINAL) ||
        (!final_result && (view->flags & JARVIS_SPEECH_RESULT_FINAL) != 0u) ||
        ((engine->backend_ops->capabilities & JARVIS_SPEECH_CAP_CONFIDENCE) != 0u &&
         (view->confidence < 0.0f || view->confidence > 1.0f ||
          view->confidence != view->confidence))) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    if (view->text_bytes > engine->config.maximum_result_bytes ||
        jarvis_speech_checked_add_u64(view->text_bytes, 1u, &required) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_OUTPUT_LIMIT;
    }
    language_length = strnlen(view->language, JARVIS_SPEECH_LANGUAGE_CAPACITY);
    if (language_length == JARVIS_SPEECH_LANGUAGE_CAPACITY) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    result->flags = view->flags;
    result->accepted_frames = accepted_frames;
    result->confidence = view->confidence;
    result->text_bytes = view->text_bytes;
    result->required_text_capacity = required;
    memcpy(result->language, view->language, language_length + 1u);
    if (required > result->text_capacity) {
        return JARVIS_SPEECH_ENGINE_BUFFER_TOO_SMALL;
    }
    if (view->text_bytes != 0u) {
        memcpy(result->text, view->text, (size_t)view->text_bytes);
    }
    result->text[view->text_bytes] = '\0';
    return JARVIS_SPEECH_ENGINE_OK;
}

static int validate_configuration(
    const JarvisSpeechEngineConfig *config,
    const JarvisSpeechBackendOps *ops) {
    const uint32_t required_capabilities = JARVIS_SPEECH_CAP_STREAMING;
    if (config == NULL || ops == NULL ||
        config->abi_version != JARVIS_SPEECH_ENGINE_ABI_VERSION ||
        config->struct_size < (uint32_t)sizeof(*config) ||
        ops->abi_version != JARVIS_SPEECH_ENGINE_ABI_VERSION ||
        ops->struct_size < (uint32_t)sizeof(*ops)) {
        return JARVIS_SPEECH_ENGINE_ABI_MISMATCH;
    }
    if (config->audio_format.sample_rate_hz != 16000u ||
        config->audio_format.channel_count != 1u ||
        config->audio_format.bits_per_sample != 16u ||
        config->minimum_chunk_frames == 0u ||
        config->maximum_chunk_frames < config->minimum_chunk_frames ||
        config->maximum_result_bytes == 0u || config->memory_budget == NULL ||
        (ops->capabilities & required_capabilities) != required_capabilities ||
        ops->open == NULL || ops->start == NULL || ops->accept_audio == NULL ||
        ops->finish == NULL || ops->cancel == NULL || ops->reset == NULL ||
        ops->close == NULL) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    return JARVIS_SPEECH_ENGINE_OK;
}

int jarvis_speech_engine_init(
    JarvisSpeechEngine *engine,
    const JarvisSpeechEngineConfig *config,
    const JarvisSpeechBackendOps *backend_ops,
    void *backend_context) {
    int status;
    if (engine == NULL) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    status = validate_configuration(config, backend_ops);
    if (status != JARVIS_SPEECH_ENGINE_OK) {
        return status;
    }
    memset(engine, 0, sizeof(*engine));
    engine->abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    engine->struct_size = (uint32_t)sizeof(*engine);
    engine->state = JARVIS_SPEECH_ENGINE_UNINITIALIZED;
    engine->config = *config;
    engine->backend_ops = backend_ops;
    engine->backend_context = backend_context;
    if (jarvis_speech_memory_set_phase(
            config->memory_budget, JARVIS_SPEECH_PHASE_LOAD) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    if (backend_ops->open(backend_context, config) != 0) {
        (void)backend_ops->close(backend_context);
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        engine->backend_ops = NULL;
        engine->backend_context = NULL;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    engine->state = JARVIS_SPEECH_ENGINE_READY;
    return JARVIS_SPEECH_ENGINE_OK;
}

int jarvis_speech_engine_start(JarvisSpeechEngine *engine) {
    if (!engine_is_live(engine)) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (engine->state != JARVIS_SPEECH_ENGINE_READY) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    if (jarvis_speech_memory_set_phase(
            engine->config.memory_budget, JARVIS_SPEECH_PHASE_LISTEN) != 0 ||
        engine->backend_ops->start(engine->backend_context) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    engine->state = JARVIS_SPEECH_ENGINE_LISTENING;
    return JARVIS_SPEECH_ENGINE_OK;
}

int jarvis_speech_engine_accept_audio(
    JarvisSpeechEngine *engine,
    const int16_t *samples,
    uint32_t frames,
    JarvisSpeechResult *result) {
    JarvisSpeechChunkPlan plan;
    JarvisSpeechBackendResultView view;
    int status;
    int backend_status;
    int release_status;
    if (!engine_is_live(engine) || samples == NULL || frames == 0u) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    status = validate_result(result);
    if (status != JARVIS_SPEECH_ENGINE_OK) {
        return status;
    }
    if (engine->state == JARVIS_SPEECH_ENGINE_CANCELLED_STATE) {
        return JARVIS_SPEECH_ENGINE_CANCELLED;
    }
    if (engine->state != JARVIS_SPEECH_ENGINE_LISTENING) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    if (frames > engine->config.maximum_chunk_frames) {
        frames = engine->config.maximum_chunk_frames;
    }
    status = jarvis_speech_plan_chunk(
        engine->config.memory_budget,
        &engine->config.chunk_cost,
        frames,
        engine->config.minimum_chunk_frames,
        &plan);
    if (status == JARVIS_SPEECH_MEMORY_LIMIT) {
        return JARVIS_SPEECH_ENGINE_MEMORY_LIMIT;
    }
    if (status != JARVIS_SPEECH_MEMORY_OK) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (jarvis_speech_memory_set_phase(
            engine->config.memory_budget, JARVIS_SPEECH_PHASE_ENCODE) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    status = jarvis_speech_memory_reserve(
        engine->config.memory_budget,
        JARVIS_SPEECH_MEM_WORKSPACE,
        plan.additional_private_bytes,
        plan.additional_physical_bytes);
    if (status == JARVIS_SPEECH_MEMORY_LIMIT) {
        return JARVIS_SPEECH_ENGINE_MEMORY_LIMIT;
    }
    if (status != JARVIS_SPEECH_MEMORY_OK) {
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    memset(&view, 0, sizeof(view));
    backend_status = engine->backend_ops->accept_audio(
        engine->backend_context, samples, plan.frames, &view);
    release_status = jarvis_speech_memory_release(
        engine->config.memory_budget,
        JARVIS_SPEECH_MEM_WORKSPACE,
        plan.additional_private_bytes,
        plan.additional_physical_bytes);
    if (release_status != JARVIS_SPEECH_MEMORY_OK) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    if (backend_status != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    return publish_result(engine, &view, plan.frames, 0, result);
}

int jarvis_speech_engine_finish(
    JarvisSpeechEngine *engine,
    JarvisSpeechResult *result) {
    JarvisSpeechBackendResultView view;
    int status;
    if (!engine_is_live(engine)) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    status = validate_result(result);
    if (status != JARVIS_SPEECH_ENGINE_OK) {
        return status;
    }
    if (engine->state == JARVIS_SPEECH_ENGINE_CANCELLED_STATE) {
        return JARVIS_SPEECH_ENGINE_CANCELLED;
    }
    if (engine->state != JARVIS_SPEECH_ENGINE_LISTENING) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    if (jarvis_speech_memory_set_phase(
            engine->config.memory_budget, JARVIS_SPEECH_PHASE_DECODE) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    memset(&view, 0, sizeof(view));
    if (engine->backend_ops->finish(engine->backend_context, &view) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    engine->state = JARVIS_SPEECH_ENGINE_FINISHED;
    return publish_result(engine, &view, 0u, 1, result);
}

int jarvis_speech_engine_cancel(JarvisSpeechEngine *engine) {
    if (!engine_is_live(engine)) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (engine->state == JARVIS_SPEECH_ENGINE_CANCELLED_STATE) {
        return JARVIS_SPEECH_ENGINE_CANCELLED;
    }
    if (engine->state != JARVIS_SPEECH_ENGINE_READY &&
        engine->state != JARVIS_SPEECH_ENGINE_LISTENING) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    if (engine->backend_ops->cancel(engine->backend_context) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    engine->state = JARVIS_SPEECH_ENGINE_CANCELLED_STATE;
    return JARVIS_SPEECH_ENGINE_OK;
}

int jarvis_speech_engine_reset(JarvisSpeechEngine *engine) {
    if (!engine_is_live(engine)) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (engine->state != JARVIS_SPEECH_ENGINE_FINISHED &&
        engine->state != JARVIS_SPEECH_ENGINE_CANCELLED_STATE &&
        engine->state != JARVIS_SPEECH_ENGINE_FAULTED) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    if ((engine->backend_ops->capabilities & JARVIS_SPEECH_CAP_RESET) == 0u ||
        engine->backend_ops->reset(engine->backend_context) != 0) {
        engine->state = JARVIS_SPEECH_ENGINE_FAULTED;
        return JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
    }
    engine->state = JARVIS_SPEECH_ENGINE_READY;
    return JARVIS_SPEECH_ENGINE_OK;
}

int jarvis_speech_engine_destroy(JarvisSpeechEngine *engine) {
    int close_status;
    if (!engine_is_live(engine)) {
        return JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT;
    }
    if (engine->state == JARVIS_SPEECH_ENGINE_DESTROYED) {
        return JARVIS_SPEECH_ENGINE_INVALID_STATE;
    }
    close_status = engine->backend_ops->close(engine->backend_context);
    engine->state = JARVIS_SPEECH_ENGINE_DESTROYED;
    engine->backend_context = NULL;
    return close_status == 0 ? JARVIS_SPEECH_ENGINE_OK
                             : JARVIS_SPEECH_ENGINE_BACKEND_ERROR;
}

const char *jarvis_speech_engine_status_name(int status) {
    switch (status) {
        case JARVIS_SPEECH_ENGINE_OK: return "ok";
        case JARVIS_SPEECH_ENGINE_BUFFER_TOO_SMALL: return "buffer-too-small";
        case JARVIS_SPEECH_ENGINE_MEMORY_LIMIT: return "memory-limit";
        case JARVIS_SPEECH_ENGINE_CANCELLED: return "cancelled";
        case JARVIS_SPEECH_ENGINE_INVALID_ARGUMENT: return "invalid-argument";
        case JARVIS_SPEECH_ENGINE_INVALID_STATE: return "invalid-state";
        case JARVIS_SPEECH_ENGINE_ABI_MISMATCH: return "abi-mismatch";
        case JARVIS_SPEECH_ENGINE_BACKEND_ERROR: return "backend-error";
        case JARVIS_SPEECH_ENGINE_OUTPUT_LIMIT: return "output-limit";
        default: return "unknown";
    }
}

const char *jarvis_speech_engine_state_name(JarvisSpeechEngineState state) {
    switch (state) {
        case JARVIS_SPEECH_ENGINE_UNINITIALIZED: return "uninitialized";
        case JARVIS_SPEECH_ENGINE_READY: return "ready";
        case JARVIS_SPEECH_ENGINE_LISTENING: return "listening";
        case JARVIS_SPEECH_ENGINE_FINISHED: return "finished";
        case JARVIS_SPEECH_ENGINE_CANCELLED_STATE: return "cancelled";
        case JARVIS_SPEECH_ENGINE_FAULTED: return "faulted";
        case JARVIS_SPEECH_ENGINE_DESTROYED: return "destroyed";
        default: return "invalid";
    }
}
