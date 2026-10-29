#include "jarvis_speech_engine.h"
#include "jarvis_speech_protocol.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <fcntl.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct FakeBackend {
    uint64_t accepted_frames;
    int opened;
} FakeBackend;

typedef enum WorkerTestHook {
    WORKER_TEST_NONE = 0,
    WORKER_TEST_EXIT_BEFORE_BOOTSTRAP,
    WORKER_TEST_EXIT_AFTER_BOOTSTRAP,
    WORKER_TEST_FAIL_LOAD,
    WORKER_TEST_EXIT_ON_AUDIO,
    WORKER_TEST_STALL_AFTER_BOOTSTRAP,
    WORKER_TEST_STALL_ON_AUDIO,
    WORKER_TEST_STALL_ON_FINISH,
    WORKER_TEST_INVALID_UTF8_PARTIAL
} WorkerTestHook;

typedef struct SpeechWorker {
    uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES];
    uint8_t nonce[JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES];
    uint8_t expected_auth[JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES];
    uint8_t payload_buffer[JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES];
    int16_t audio_buffer[JARVIS_SPEECH_PROTOCOL_MAX_AUDIO_BYTES / 2u];
    char result_text[JARVIS_SPEECH_PROTOCOL_MAX_TEXT_BYTES + 1u];
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolSequencer input_sequencer;
    JarvisSpeechMemoryBudget memory_budget;
    JarvisSpeechEngine engine;
    JarvisSpeechBackendOps backend_ops;
    FakeBackend backend;
    uint64_t output_sequence;
    int authenticated;
    int engine_loaded;
    WorkerTestHook test_hook;
} SpeechWorker;

static const char PARTIAL_TEXT[] = "calculator";
static const char FINAL_TEXT[] = "calculator open pannu";

static void write_u32_le(uint8_t *output, uint32_t value) {
    output[0] = (uint8_t)(value & 0xffu);
    output[1] = (uint8_t)((value >> 8u) & 0xffu);
    output[2] = (uint8_t)((value >> 16u) & 0xffu);
    output[3] = (uint8_t)((value >> 24u) & 0xffu);
}

static int write_all(const void *data, size_t data_bytes) {
    const uint8_t *bytes = (const uint8_t *)data;
    size_t offset = 0u;
    int written;
    while (offset < data_bytes) {
        written = _write(_fileno(stdout), bytes + offset,
                         (unsigned int)(data_bytes - offset));
        if (written <= 0) {
            return -1;
        }
        offset += (size_t)written;
    }
    return 0;
}

static int send_frame(
    SpeechWorker *worker,
    uint16_t message_type,
    const void *payload,
    uint32_t payload_bytes) {
    JarvisSpeechProtocolHeader header;
    uint8_t encoded[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    uint64_t sequence;
    if (worker == NULL || (payload == NULL && payload_bytes != 0u) ||
        worker->output_sequence == UINT64_MAX) {
        return -1;
    }
    sequence = worker->output_sequence + 1u;
    memset(&header, 0, sizeof(header));
    header.message_type = message_type;
    header.payload_bytes = payload_bytes;
    memcpy(header.session_id, worker->session_id, sizeof(header.session_id));
    header.sequence = sequence;
    if (jarvis_speech_protocol_encode_header(
            &header, encoded, sizeof(encoded)) != JARVIS_SPEECH_PROTOCOL_OK ||
        write_all(encoded, sizeof(encoded)) != 0 ||
        (payload_bytes != 0u && write_all(payload, payload_bytes) != 0)) {
        return -1;
    }
    worker->output_sequence = sequence;
    return 0;
}

static int worker_fail(SpeechWorker *worker, const char *safe_message) {
    size_t length = strlen(safe_message);
    if (length <= JARVIS_SPEECH_PROTOCOL_MAX_CONTROL_BYTES) {
        (void)send_frame(worker, JARVIS_SPEECH_MSG_ERROR, safe_message,
                         (uint32_t)length);
    }
    return -1;
}

static int fake_open(
    void *backend_context,
    const JarvisSpeechEngineConfig *config) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    (void)config;
    backend->opened = 1;
    backend->accepted_frames = 0u;
    return 0;
}

static int fake_start(void *backend_context) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    backend->accepted_frames = 0u;
    return backend->opened ? 0 : -1;
}

static int fake_accept(
    void *backend_context,
    const int16_t *samples,
    uint32_t frames,
    JarvisSpeechBackendResultView *result) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    (void)samples;
    backend->accepted_frames += frames;
    memset(result, 0, sizeof(*result));
    result->text = PARTIAL_TEXT;
    result->text_bytes = (uint64_t)(sizeof(PARTIAL_TEXT) - 1u);
    result->confidence = 0.875f;
    result->flags = JARVIS_SPEECH_RESULT_PARTIAL;
    memcpy(result->language, "ta-en", 6u);
    return 0;
}

static int fake_finish(
    void *backend_context,
    JarvisSpeechBackendResultView *result) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    if (!backend->opened) {
        return -1;
    }
    memset(result, 0, sizeof(*result));
    result->text = FINAL_TEXT;
    result->text_bytes = (uint64_t)(sizeof(FINAL_TEXT) - 1u);
    result->confidence = 0.875f;
    result->flags = JARVIS_SPEECH_RESULT_FINAL;
    memcpy(result->language, "ta-en", 6u);
    return 0;
}

static int fake_cancel(void *backend_context) {
    return ((FakeBackend *)backend_context)->opened ? 0 : -1;
}

static int fake_reset(void *backend_context) {
    FakeBackend *backend = (FakeBackend *)backend_context;
    backend->accepted_frames = 0u;
    return backend->opened ? 0 : -1;
}

static int fake_close(void *backend_context) {
    ((FakeBackend *)backend_context)->opened = 0;
    return 0;
}

static JarvisSpeechBackendOps make_backend_ops(void) {
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

static int load_fake_engine(SpeechWorker *worker) {
    JarvisSpeechEngineConfig config;
    memset(&config, 0, sizeof(config));
    worker->backend_ops = make_backend_ops();
    jarvis_speech_memory_init(
        &worker->memory_budget, 16u * 1024u * 1024u, 16u * 1024u * 1024u);
    config.abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    config.struct_size = (uint32_t)sizeof(config);
    config.audio_format.sample_rate_hz = 16000u;
    config.audio_format.channel_count = 1u;
    config.audio_format.bits_per_sample = 16u;
    config.minimum_chunk_frames = 1u;
    config.maximum_chunk_frames = JARVIS_SPEECH_PROTOCOL_MAX_AUDIO_BYTES / 2u;
    config.maximum_result_bytes = JARVIS_SPEECH_PROTOCOL_MAX_TEXT_BYTES;
    config.chunk_cost.fixed_private_bytes = 64u * 1024u;
    config.chunk_cost.fixed_physical_bytes = 64u * 1024u;
    config.chunk_cost.private_bytes_per_frame = 8u;
    config.chunk_cost.physical_bytes_per_frame = 8u;
    config.memory_budget = &worker->memory_budget;
    if (jarvis_speech_engine_init(
            &worker->engine, &config, &worker->backend_ops, &worker->backend) !=
        JARVIS_SPEECH_ENGINE_OK) {
        return -1;
    }
    worker->engine_loaded = 1;
    return 0;
}

static JarvisSpeechResult make_result(SpeechWorker *worker) {
    JarvisSpeechResult result;
    memset(&result, 0, sizeof(result));
    result.abi_version = JARVIS_SPEECH_ENGINE_ABI_VERSION;
    result.struct_size = (uint32_t)sizeof(result);
    result.text = worker->result_text;
    result.text_capacity = sizeof(worker->result_text);
    return result;
}

static int bytes_equal(const uint8_t *left, const uint8_t *right, size_t count) {
    uint8_t difference = 0u;
    size_t index;
    for (index = 0u; index < count; ++index) {
        difference = (uint8_t)(difference | (left[index] ^ right[index]));
    }
    return difference == 0u;
}

static int handle_frame(
    SpeechWorker *worker,
    const JarvisSpeechProtocolFrame *frame) {
    JarvisSpeechResult result;
    int status;
    if (jarvis_speech_protocol_sequencer_accept(
            &worker->input_sequencer, &frame->header) !=
        JARVIS_SPEECH_PROTOCOL_OK) {
        return worker_fail(worker, "session or sequence rejected");
    }
    if (!worker->authenticated) {
        if (frame->header.message_type == JARVIS_SPEECH_MSG_SHUTDOWN &&
            frame->header.payload_bytes == 0u) {
            return 1;
        }
        if (frame->header.message_type != JARVIS_SPEECH_MSG_START_AUTH ||
            frame->header.payload_bytes !=
                JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES ||
            !bytes_equal(frame->payload, worker->expected_auth,
                         JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES)) {
            return worker_fail(worker, "start authorization rejected");
        }
        if (worker->test_hook == WORKER_TEST_FAIL_LOAD) {
            return worker_fail(worker, "backend load failed");
        }
        if (load_fake_engine(worker) != 0) {
            return worker_fail(worker, "backend load failed");
        }
        worker->authenticated = 1;
        return send_frame(worker, JARVIS_SPEECH_MSG_READY, NULL, 0u);
    }

    switch ((JarvisSpeechMessageType)frame->header.message_type) {
        case JARVIS_SPEECH_MSG_START_SESSION:
            if (jarvis_speech_engine_start(&worker->engine) !=
                JARVIS_SPEECH_ENGINE_OK) {
                return worker_fail(worker, "start session rejected");
            }
            return send_frame(worker, JARVIS_SPEECH_MSG_READY, NULL, 0u);
        case JARVIS_SPEECH_MSG_AUDIO:
            if (worker->test_hook == WORKER_TEST_EXIT_ON_AUDIO) {
                ExitProcess(72u);
            }
            if (worker->test_hook == WORKER_TEST_STALL_ON_AUDIO) {
                Sleep(INFINITE);
            }
            memcpy(worker->audio_buffer, frame->payload,
                   frame->header.payload_bytes);
            result = make_result(worker);
            status = jarvis_speech_engine_accept_audio(
                &worker->engine, worker->audio_buffer,
                frame->header.payload_bytes / 2u, &result);
            if (status != JARVIS_SPEECH_ENGINE_OK) {
                return worker_fail(worker, "audio rejected");
            }
            if (worker->test_hook == WORKER_TEST_INVALID_UTF8_PARTIAL) {
                static const uint8_t invalid_utf8[] = {0xc0u, 0xafu};
                return send_frame(worker, JARVIS_SPEECH_MSG_PARTIAL,
                                  invalid_utf8,
                                  (uint32_t)sizeof(invalid_utf8));
            }
            return send_frame(worker, JARVIS_SPEECH_MSG_PARTIAL,
                              result.text, (uint32_t)result.text_bytes);
        case JARVIS_SPEECH_MSG_FINISH:
            if (worker->test_hook == WORKER_TEST_STALL_ON_FINISH) {
                Sleep(INFINITE);
            }
            result = make_result(worker);
            status = jarvis_speech_engine_finish(&worker->engine, &result);
            if (status != JARVIS_SPEECH_ENGINE_OK) {
                return worker_fail(worker, "finish rejected");
            }
            return send_frame(worker, JARVIS_SPEECH_MSG_FINAL,
                              result.text, (uint32_t)result.text_bytes);
        case JARVIS_SPEECH_MSG_CANCEL:
            status = jarvis_speech_engine_cancel(&worker->engine);
            if (status != JARVIS_SPEECH_ENGINE_OK &&
                status != JARVIS_SPEECH_ENGINE_CANCELLED) {
                return worker_fail(worker, "cancel rejected");
            }
            return send_frame(worker, JARVIS_SPEECH_MSG_CANCEL, NULL, 0u);
        case JARVIS_SPEECH_MSG_RESET:
            if (jarvis_speech_engine_reset(&worker->engine) !=
                JARVIS_SPEECH_ENGINE_OK) {
                return worker_fail(worker, "reset rejected");
            }
            return send_frame(worker, JARVIS_SPEECH_MSG_READY, NULL, 0u);
        case JARVIS_SPEECH_MSG_SHUTDOWN:
            return 1;
        default:
            return worker_fail(worker, "protocol state violation");
    }
}

static int make_auth_challenge(SpeechWorker *worker) {
    static const uint8_t label[] = JARVIS_SPEECH_PROTOCOL_AUTH_LABEL;
    uint8_t material[(sizeof(label) - 1u) +
                     JARVIS_SPEECH_PROTOCOL_SESSION_BYTES +
                     JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES];
    size_t offset = 0u;
    BCRYPT_ALG_HANDLE algorithm = NULL;
    NTSTATUS status;
    status = BCryptGenRandom(NULL, worker->session_id,
                             (ULONG)sizeof(worker->session_id),
                             BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status < 0) {
        return -1;
    }
    status = BCryptGenRandom(NULL, worker->nonce,
                             (ULONG)sizeof(worker->nonce),
                             BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status < 0) {
        return -1;
    }
    memcpy(material + offset, label, sizeof(label) - 1u);
    offset += sizeof(label) - 1u;
    memcpy(material + offset, worker->session_id, sizeof(worker->session_id));
    offset += sizeof(worker->session_id);
    memcpy(material + offset, worker->nonce, sizeof(worker->nonce));
    status = BCryptOpenAlgorithmProvider(
        &algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0u);
    if (status < 0) {
        return -1;
    }
    status = BCryptHash(algorithm, NULL, 0u, material, (ULONG)sizeof(material),
                        worker->expected_auth,
                        (ULONG)sizeof(worker->expected_auth));
    (void)BCryptCloseAlgorithmProvider(algorithm, 0u);
    return status < 0 ? -1 : 0;
}

static int send_bootstrap(SpeechWorker *worker) {
    uint8_t payload[JARVIS_SPEECH_PROTOCOL_BOOTSTRAP_BYTES];
    memset(payload, 0, sizeof(payload));
    write_u32_le(payload, GetCurrentProcessId());
    write_u32_le(payload + 4u,
                 JARVIS_SPEECH_WORKER_CAP_FAKE_BACKEND |
                 JARVIS_SPEECH_WORKER_CAP_AUTH_CHALLENGE);
    memcpy(payload + 8u, worker->nonce, sizeof(worker->nonce));
    return send_frame(worker, JARVIS_SPEECH_MSG_BOOTSTRAP,
                      payload, (uint32_t)sizeof(payload));
}

static int parse_test_hook(
    int argument_count,
    char **arguments,
    WorkerTestHook *test_hook) {
    if (test_hook == NULL || arguments == NULL || argument_count < 1) {
        return -1;
    }
    *test_hook = WORKER_TEST_NONE;
    if (argument_count == 1) {
        return 0;
    }
#if defined(JARVIS_SPEECH_ENABLE_TEST_HOOKS)
    if (argument_count != 2) {
        return -1;
    }
    if (strcmp(arguments[1], "--test-exit-before-bootstrap") == 0) {
        *test_hook = WORKER_TEST_EXIT_BEFORE_BOOTSTRAP;
    } else if (strcmp(arguments[1], "--test-exit-after-bootstrap") == 0) {
        *test_hook = WORKER_TEST_EXIT_AFTER_BOOTSTRAP;
    } else if (strcmp(arguments[1], "--test-fail-load") == 0) {
        *test_hook = WORKER_TEST_FAIL_LOAD;
    } else if (strcmp(arguments[1], "--test-exit-on-audio") == 0) {
        *test_hook = WORKER_TEST_EXIT_ON_AUDIO;
    } else if (strcmp(arguments[1], "--test-stall-after-bootstrap") == 0) {
        *test_hook = WORKER_TEST_STALL_AFTER_BOOTSTRAP;
    } else if (strcmp(arguments[1], "--test-stall-on-audio") == 0) {
        *test_hook = WORKER_TEST_STALL_ON_AUDIO;
    } else if (strcmp(arguments[1], "--test-stall-on-finish") == 0) {
        *test_hook = WORKER_TEST_STALL_ON_FINISH;
    } else if (strcmp(arguments[1], "--test-invalid-utf8-partial") == 0) {
        *test_hook = WORKER_TEST_INVALID_UTF8_PARTIAL;
    } else {
        return -1;
    }
    return 0;
#else
    (void)argument_count;
    return -1;
#endif
}

int main(int argument_count, char **arguments) {
    static SpeechWorker worker;
    uint8_t input[4096];
    JarvisSpeechProtocolFrame frame;
    size_t offset;
    size_t consumed;
    int received;
    int status;
    int exit_code = 4;
    if (parse_test_hook(
            argument_count, arguments, &worker.test_hook) != 0) {
        return 2;
    }
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
        _setmode(_fileno(stdout), _O_BINARY) == -1) {
        return 2;
    }
    if (worker.test_hook == WORKER_TEST_EXIT_BEFORE_BOOTSTRAP) {
        return 70;
    }
    if (make_auth_challenge(&worker) != 0 ||
        jarvis_speech_protocol_parser_init(
            &worker.parser, worker.payload_buffer,
            sizeof(worker.payload_buffer)) != JARVIS_SPEECH_PROTOCOL_OK ||
        jarvis_speech_protocol_sequencer_init(
            &worker.input_sequencer, worker.session_id) !=
            JARVIS_SPEECH_PROTOCOL_OK ||
        send_bootstrap(&worker) != 0) {
        return 2;
    }
    if (worker.test_hook == WORKER_TEST_EXIT_AFTER_BOOTSTRAP) {
        return 71;
    }
    if (worker.test_hook == WORKER_TEST_STALL_AFTER_BOOTSTRAP) {
        Sleep(INFINITE);
    }

    for (;;) {
        received = _read(_fileno(stdin), input, (unsigned int)sizeof(input));
        if (received <= 0) {
            exit_code = 4;
            break;
        }
        offset = 0u;
        while (offset < (size_t)received) {
            status = jarvis_speech_protocol_feed(
                &worker.parser, input + offset, (size_t)received - offset,
                &consumed, &frame);
            offset += consumed;
            if (status == JARVIS_SPEECH_PROTOCOL_NEED_MORE) {
                break;
            }
            if (status != JARVIS_SPEECH_PROTOCOL_FRAME_READY) {
                (void)worker_fail(&worker, "invalid protocol frame");
                exit_code = 3;
                goto cleanup;
            }
            status = handle_frame(&worker, &frame);
            if (status > 0) {
                exit_code = 0;
                goto cleanup;
            }
            if (status < 0) {
                exit_code = 3;
                goto cleanup;
            }
        }
    }

cleanup:
    if (worker.engine_loaded) {
        (void)jarvis_speech_engine_destroy(&worker.engine);
    }
    if (exit_code != 0) {
        fprintf(stderr, "Jarvis speech worker stopped with code %d\n", exit_code);
    }
    return exit_code;
}
