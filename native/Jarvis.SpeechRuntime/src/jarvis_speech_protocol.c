#include "jarvis_speech_protocol.h"

#include <limits.h>
#include <string.h>

static uint16_t read_u16_le(const uint8_t *input) {
    return (uint16_t)((uint16_t)input[0] |
                      ((uint16_t)input[1] << 8u));
}

static uint32_t read_u32_le(const uint8_t *input) {
    return (uint32_t)input[0] |
           ((uint32_t)input[1] << 8u) |
           ((uint32_t)input[2] << 16u) |
           ((uint32_t)input[3] << 24u);
}

static uint64_t read_u64_le(const uint8_t *input) {
    uint64_t value = 0u;
    unsigned int index;
    for (index = 0u; index < 8u; ++index) {
        value |= (uint64_t)input[index] << (index * 8u);
    }
    return value;
}

static void write_u16_le(uint8_t *output, uint16_t value) {
    output[0] = (uint8_t)(value & 0xffu);
    output[1] = (uint8_t)((value >> 8u) & 0xffu);
}

static void write_u32_le(uint8_t *output, uint32_t value) {
    output[0] = (uint8_t)(value & 0xffu);
    output[1] = (uint8_t)((value >> 8u) & 0xffu);
    output[2] = (uint8_t)((value >> 16u) & 0xffu);
    output[3] = (uint8_t)((value >> 24u) & 0xffu);
}

static void write_u64_le(uint8_t *output, uint64_t value) {
    unsigned int index;
    for (index = 0u; index < 8u; ++index) {
        output[index] = (uint8_t)((value >> (index * 8u)) & 0xffu);
    }
}

static int session_is_zero(
    const uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES]) {
    uint8_t combined = 0u;
    size_t index;
    for (index = 0u; index < JARVIS_SPEECH_PROTOCOL_SESSION_BYTES; ++index) {
        combined = (uint8_t)(combined | session_id[index]);
    }
    return combined == 0u;
}

static int message_type_known(uint16_t message_type) {
    return message_type >= (uint16_t)JARVIS_SPEECH_MSG_HELLO &&
           message_type <= (uint16_t)JARVIS_SPEECH_MSG_SHUTDOWN;
}

static int validate_payload_size(const JarvisSpeechProtocolHeader *header) {
    switch ((JarvisSpeechMessageType)header->message_type) {
        case JARVIS_SPEECH_MSG_HELLO:
        case JARVIS_SPEECH_MSG_START_SESSION:
        case JARVIS_SPEECH_MSG_FINISH:
        case JARVIS_SPEECH_MSG_CANCEL:
        case JARVIS_SPEECH_MSG_RESET:
        case JARVIS_SPEECH_MSG_SHUTDOWN:
            return header->payload_bytes == 0u
                ? JARVIS_SPEECH_PROTOCOL_OK
                : JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
        case JARVIS_SPEECH_MSG_AUDIO:
            if (header->payload_bytes == 0u ||
                header->payload_bytes > JARVIS_SPEECH_PROTOCOL_MAX_AUDIO_BYTES ||
                (header->payload_bytes & 1u) != 0u) {
                return JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
            }
            return JARVIS_SPEECH_PROTOCOL_OK;
        case JARVIS_SPEECH_MSG_PARTIAL:
        case JARVIS_SPEECH_MSG_FINAL:
            return header->payload_bytes <= JARVIS_SPEECH_PROTOCOL_MAX_TEXT_BYTES
                ? JARVIS_SPEECH_PROTOCOL_OK
                : JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
        case JARVIS_SPEECH_MSG_ERROR:
            return header->payload_bytes <= JARVIS_SPEECH_PROTOCOL_MAX_CONTROL_BYTES
                ? JARVIS_SPEECH_PROTOCOL_OK
                : JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
        case JARVIS_SPEECH_MSG_BOOTSTRAP:
        case JARVIS_SPEECH_MSG_START_AUTH:
        case JARVIS_SPEECH_MSG_READY:
        case JARVIS_SPEECH_MSG_STATS:
            return header->payload_bytes <= JARVIS_SPEECH_PROTOCOL_MAX_CONTROL_BYTES
                ? JARVIS_SPEECH_PROTOCOL_OK
                : JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
        default:
            return JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
    }
}

static int validate_payload_content(
    const JarvisSpeechProtocolHeader *header,
    const uint8_t *payload) {
    int status = validate_payload_size(header);
    if (status != JARVIS_SPEECH_PROTOCOL_OK) {
        return status;
    }
    if (header->message_type == (uint16_t)JARVIS_SPEECH_MSG_PARTIAL ||
        header->message_type == (uint16_t)JARVIS_SPEECH_MSG_FINAL ||
        header->message_type == (uint16_t)JARVIS_SPEECH_MSG_ERROR) {
        if (!jarvis_speech_protocol_utf8_valid(
                payload, (size_t)header->payload_bytes)) {
            return JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD;
        }
    }
    return JARVIS_SPEECH_PROTOCOL_OK;
}

static void decode_header(
    const uint8_t input[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES],
    JarvisSpeechProtocolHeader *header) {
    header->message_type = read_u16_le(input + 8u);
    header->flags = read_u16_le(input + 10u);
    header->payload_bytes = read_u32_le(input + 12u);
    memcpy(header->session_id, input + 16u, JARVIS_SPEECH_PROTOCOL_SESSION_BYTES);
    header->sequence = read_u64_le(input + 32u);
}

int jarvis_speech_protocol_parser_init(
    JarvisSpeechProtocolParser *parser,
    void *payload_buffer,
    size_t payload_capacity) {
    if (parser == NULL || payload_buffer == NULL || payload_capacity == 0u ||
        payload_capacity > JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    memset(parser, 0, sizeof(*parser));
    parser->payload_buffer = (uint8_t *)payload_buffer;
    parser->payload_capacity = payload_capacity;
    return JARVIS_SPEECH_PROTOCOL_OK;
}

int jarvis_speech_protocol_validate_header(
    const JarvisSpeechProtocolHeader *header,
    size_t payload_capacity) {
    if (header == NULL || payload_capacity == 0u ||
        payload_capacity > JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    if (!message_type_known(header->message_type) || header->flags != 0u ||
        header->sequence == 0u || session_is_zero(header->session_id)) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_HEADER;
    }
    if (header->payload_bytes > JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES ||
        (size_t)header->payload_bytes > payload_capacity) {
        return JARVIS_SPEECH_PROTOCOL_PAYLOAD_LIMIT;
    }
    return validate_payload_size(header);
}

int jarvis_speech_protocol_feed(
    JarvisSpeechProtocolParser *parser,
    const void *data,
    size_t data_bytes,
    size_t *consumed_bytes,
    JarvisSpeechProtocolFrame *out_frame) {
    const uint8_t *input = (const uint8_t *)data;
    size_t consumed = 0u;
    size_t copy_bytes;
    int status;
    if (consumed_bytes != NULL) {
        *consumed_bytes = 0u;
    }
    if (parser == NULL || consumed_bytes == NULL || out_frame == NULL ||
        (data == NULL && data_bytes != 0u)) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    if (parser->faulted) {
        return JARVIS_SPEECH_PROTOCOL_FAULTED;
    }
    memset(out_frame, 0, sizeof(*out_frame));
    if (!parser->header_decoded) {
        copy_bytes = JARVIS_SPEECH_PROTOCOL_HEADER_BYTES - parser->header_used;
        if (copy_bytes > data_bytes) {
            copy_bytes = data_bytes;
        }
        if (copy_bytes != 0u) {
            memcpy(parser->header_buffer + parser->header_used, input, copy_bytes);
            parser->header_used += copy_bytes;
            consumed += copy_bytes;
        }
        if (parser->header_used != JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) {
            *consumed_bytes = consumed;
            return JARVIS_SPEECH_PROTOCOL_NEED_MORE;
        }
        if (read_u32_le(parser->header_buffer) != JARVIS_SPEECH_PROTOCOL_MAGIC ||
            read_u16_le(parser->header_buffer + 4u) !=
                JARVIS_SPEECH_PROTOCOL_VERSION ||
            read_u16_le(parser->header_buffer + 6u) !=
                JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) {
            parser->faulted = 1;
            *consumed_bytes = consumed;
            return JARVIS_SPEECH_PROTOCOL_INVALID_HEADER;
        }
        decode_header(parser->header_buffer, &parser->current_header);
        status = jarvis_speech_protocol_validate_header(
            &parser->current_header, parser->payload_capacity);
        if (status != JARVIS_SPEECH_PROTOCOL_OK) {
            parser->faulted = 1;
            *consumed_bytes = consumed;
            return status;
        }
        parser->header_decoded = 1;
    }
    copy_bytes = (size_t)parser->current_header.payload_bytes -
                 parser->payload_used;
    if (copy_bytes > data_bytes - consumed) {
        copy_bytes = data_bytes - consumed;
    }
    if (copy_bytes != 0u) {
        memcpy(parser->payload_buffer + parser->payload_used,
               input + consumed, copy_bytes);
        parser->payload_used += copy_bytes;
        consumed += copy_bytes;
    }
    if (parser->payload_used != (size_t)parser->current_header.payload_bytes) {
        *consumed_bytes = consumed;
        return JARVIS_SPEECH_PROTOCOL_NEED_MORE;
    }
    status = validate_payload_content(
        &parser->current_header, parser->payload_buffer);
    if (status != JARVIS_SPEECH_PROTOCOL_OK) {
        parser->faulted = 1;
        *consumed_bytes = consumed;
        return status;
    }
    out_frame->header = parser->current_header;
    out_frame->payload = parser->current_header.payload_bytes == 0u
        ? NULL
        : parser->payload_buffer;
    parser->header_used = 0u;
    parser->payload_used = 0u;
    parser->header_decoded = 0;
    memset(&parser->current_header, 0, sizeof(parser->current_header));
    *consumed_bytes = consumed;
    return JARVIS_SPEECH_PROTOCOL_FRAME_READY;
}

int jarvis_speech_protocol_encode_header(
    const JarvisSpeechProtocolHeader *header,
    void *output,
    size_t output_capacity) {
    uint8_t *bytes = (uint8_t *)output;
    int status;
    if (header == NULL || output == NULL ||
        output_capacity < JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    status = jarvis_speech_protocol_validate_header(
        header, JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES);
    if (status != JARVIS_SPEECH_PROTOCOL_OK) {
        return status;
    }
    memset(bytes, 0, JARVIS_SPEECH_PROTOCOL_HEADER_BYTES);
    write_u32_le(bytes, JARVIS_SPEECH_PROTOCOL_MAGIC);
    write_u16_le(bytes + 4u, JARVIS_SPEECH_PROTOCOL_VERSION);
    write_u16_le(bytes + 6u, JARVIS_SPEECH_PROTOCOL_HEADER_BYTES);
    write_u16_le(bytes + 8u, header->message_type);
    write_u16_le(bytes + 10u, header->flags);
    write_u32_le(bytes + 12u, header->payload_bytes);
    memcpy(bytes + 16u, header->session_id,
           JARVIS_SPEECH_PROTOCOL_SESSION_BYTES);
    write_u64_le(bytes + 32u, header->sequence);
    return JARVIS_SPEECH_PROTOCOL_OK;
}

int jarvis_speech_protocol_utf8_valid(const void *data, size_t data_bytes) {
    const uint8_t *bytes = (const uint8_t *)data;
    size_t index = 0u;
    uint32_t codepoint;
    unsigned int continuation_count;
    unsigned int offset;
    if (data == NULL && data_bytes != 0u) {
        return 0;
    }
    while (index < data_bytes) {
        if (bytes[index] == 0u) {
            return 0;
        }
        if (bytes[index] <= 0x7fu) {
            ++index;
            continue;
        }
        if (bytes[index] >= 0xc2u && bytes[index] <= 0xdfu) {
            codepoint = (uint32_t)(bytes[index] & 0x1fu);
            continuation_count = 1u;
        } else if (bytes[index] >= 0xe0u && bytes[index] <= 0xefu) {
            codepoint = (uint32_t)(bytes[index] & 0x0fu);
            continuation_count = 2u;
        } else if (bytes[index] >= 0xf0u && bytes[index] <= 0xf4u) {
            codepoint = (uint32_t)(bytes[index] & 0x07u);
            continuation_count = 3u;
        } else {
            return 0;
        }
        if (data_bytes - index - 1u < continuation_count) {
            return 0;
        }
        for (offset = 1u; offset <= continuation_count; ++offset) {
            if ((bytes[index + offset] & 0xc0u) != 0x80u) {
                return 0;
            }
            codepoint = (codepoint << 6u) |
                        (uint32_t)(bytes[index + offset] & 0x3fu);
        }
        if ((continuation_count == 2u && codepoint < 0x800u) ||
            (continuation_count == 3u && codepoint < 0x10000u) ||
            (codepoint >= 0xd800u && codepoint <= 0xdfffu) ||
            codepoint > 0x10ffffu) {
            return 0;
        }
        index += (size_t)continuation_count + 1u;
    }
    return 1;
}

int jarvis_speech_protocol_sequencer_init(
    JarvisSpeechProtocolSequencer *sequencer,
    const uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES]) {
    if (sequencer == NULL || session_id == NULL || session_is_zero(session_id)) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    memset(sequencer, 0, sizeof(*sequencer));
    memcpy(sequencer->session_id, session_id,
           JARVIS_SPEECH_PROTOCOL_SESSION_BYTES);
    sequencer->initialized = 1;
    return JARVIS_SPEECH_PROTOCOL_OK;
}

int jarvis_speech_protocol_sequencer_accept(
    JarvisSpeechProtocolSequencer *sequencer,
    const JarvisSpeechProtocolHeader *header) {
    uint64_t expected;
    if (sequencer == NULL || header == NULL || !sequencer->initialized) {
        return JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT;
    }
    if (memcmp(sequencer->session_id, header->session_id,
               JARVIS_SPEECH_PROTOCOL_SESSION_BYTES) != 0) {
        return JARVIS_SPEECH_PROTOCOL_SESSION_MISMATCH;
    }
    if (sequencer->last_sequence == UINT64_MAX) {
        return JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH;
    }
    expected = sequencer->last_sequence + 1u;
    if (header->sequence != expected) {
        return JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH;
    }
    sequencer->last_sequence = header->sequence;
    return JARVIS_SPEECH_PROTOCOL_OK;
}

const char *jarvis_speech_protocol_status_name(int status) {
    switch (status) {
        case JARVIS_SPEECH_PROTOCOL_OK: return "ok";
        case JARVIS_SPEECH_PROTOCOL_NEED_MORE: return "need-more";
        case JARVIS_SPEECH_PROTOCOL_FRAME_READY: return "frame-ready";
        case JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT: return "invalid-argument";
        case JARVIS_SPEECH_PROTOCOL_INVALID_HEADER: return "invalid-header";
        case JARVIS_SPEECH_PROTOCOL_PAYLOAD_LIMIT: return "payload-limit";
        case JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD: return "invalid-payload";
        case JARVIS_SPEECH_PROTOCOL_SESSION_MISMATCH: return "session-mismatch";
        case JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH: return "sequence-mismatch";
        case JARVIS_SPEECH_PROTOCOL_FAULTED: return "faulted";
        default: return "unknown";
    }
}

const char *jarvis_speech_message_type_name(uint16_t message_type) {
    switch ((JarvisSpeechMessageType)message_type) {
        case JARVIS_SPEECH_MSG_HELLO: return "hello";
        case JARVIS_SPEECH_MSG_BOOTSTRAP: return "bootstrap";
        case JARVIS_SPEECH_MSG_START_AUTH: return "start-auth";
        case JARVIS_SPEECH_MSG_READY: return "ready";
        case JARVIS_SPEECH_MSG_START_SESSION: return "start-session";
        case JARVIS_SPEECH_MSG_AUDIO: return "audio";
        case JARVIS_SPEECH_MSG_PARTIAL: return "partial";
        case JARVIS_SPEECH_MSG_FINISH: return "finish";
        case JARVIS_SPEECH_MSG_FINAL: return "final";
        case JARVIS_SPEECH_MSG_CANCEL: return "cancel";
        case JARVIS_SPEECH_MSG_RESET: return "reset";
        case JARVIS_SPEECH_MSG_STATS: return "stats";
        case JARVIS_SPEECH_MSG_ERROR: return "error";
        case JARVIS_SPEECH_MSG_SHUTDOWN: return "shutdown";
        default: return "invalid";
    }
}
