#include "jarvis_speech_protocol.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

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

static void make_session(uint8_t session[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES]) {
    size_t index;
    for (index = 0u; index < JARVIS_SPEECH_PROTOCOL_SESSION_BYTES; ++index) {
        session[index] = (uint8_t)(index + 1u);
    }
}

static JarvisSpeechProtocolHeader make_header(
    uint16_t message_type,
    uint32_t payload_bytes,
    uint64_t sequence) {
    JarvisSpeechProtocolHeader header;
    memset(&header, 0, sizeof(header));
    header.message_type = message_type;
    header.payload_bytes = payload_bytes;
    header.sequence = sequence;
    make_session(header.session_id);
    return header;
}

static void test_fragmented_frame(void) {
    const uint8_t payload[] = "calculator";
    uint8_t encoded[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    uint8_t storage[64];
    JarvisSpeechProtocolHeader header = make_header(
        JARVIS_SPEECH_MSG_PARTIAL, (uint32_t)(sizeof(payload) - 1u), 1u);
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed;
    size_t index;
    int status = 0;
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    for (index = 0u; index < sizeof(encoded); ++index) {
        status = jarvis_speech_protocol_feed(
            &parser, encoded + index, 1u, &consumed, &frame);
        CHECK(consumed == 1u);
        CHECK(status == JARVIS_SPEECH_PROTOCOL_NEED_MORE);
    }
    for (index = 0u; index < sizeof(payload) - 1u; ++index) {
        status = jarvis_speech_protocol_feed(
            &parser, payload + index, 1u, &consumed, &frame);
        CHECK(consumed == 1u);
        if (index + 1u == sizeof(payload) - 1u) {
            CHECK(status == JARVIS_SPEECH_PROTOCOL_FRAME_READY);
        } else {
            CHECK(status == JARVIS_SPEECH_PROTOCOL_NEED_MORE);
        }
    }
    CHECK(frame.header.message_type == JARVIS_SPEECH_MSG_PARTIAL);
    CHECK(frame.header.sequence == 1u);
    CHECK(frame.header.payload_bytes == sizeof(payload) - 1u);
    CHECK(memcmp(frame.payload, payload, sizeof(payload) - 1u) == 0);
}

static void test_coalesced_frames(void) {
    const uint8_t error_payload[] = "safe error";
    uint8_t input[(JARVIS_SPEECH_PROTOCOL_HEADER_BYTES * 2u) +
                  sizeof(error_payload) - 1u];
    uint8_t storage[64];
    JarvisSpeechProtocolHeader hello = make_header(
        JARVIS_SPEECH_MSG_HELLO, 0u, 1u);
    JarvisSpeechProtocolHeader error = make_header(
        JARVIS_SPEECH_MSG_ERROR, (uint32_t)(sizeof(error_payload) - 1u), 2u);
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed;
    size_t offset = 0u;
    CHECK(jarvis_speech_protocol_encode_header(
              &hello, input, JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_encode_header(
              &error, input + JARVIS_SPEECH_PROTOCOL_HEADER_BYTES,
              JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    memcpy(input + (JARVIS_SPEECH_PROTOCOL_HEADER_BYTES * 2u),
           error_payload, sizeof(error_payload) - 1u);
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, input, sizeof(input), &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_FRAME_READY);
    CHECK(consumed == JARVIS_SPEECH_PROTOCOL_HEADER_BYTES);
    CHECK(frame.header.message_type == JARVIS_SPEECH_MSG_HELLO &&
          frame.payload == NULL);
    offset += consumed;
    CHECK(jarvis_speech_protocol_feed(
              &parser, input + offset, sizeof(input) - offset,
              &consumed, &frame) == JARVIS_SPEECH_PROTOCOL_FRAME_READY);
    CHECK(consumed == JARVIS_SPEECH_PROTOCOL_HEADER_BYTES +
                      sizeof(error_payload) - 1u);
    CHECK(frame.header.message_type == JARVIS_SPEECH_MSG_ERROR);
    CHECK(memcmp(frame.payload, error_payload, sizeof(error_payload) - 1u) == 0);
}

static void test_invalid_headers_and_limits(void) {
    uint8_t encoded[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    uint8_t storage[64];
    JarvisSpeechProtocolHeader header = make_header(
        JARVIS_SPEECH_MSG_HELLO, 0u, 1u);
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed;
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    encoded[0] ^= 0xffu;
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, encoded, sizeof(encoded), &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_HEADER);
    CHECK(parser.faulted == 1 && consumed == sizeof(encoded));
    CHECK(jarvis_speech_protocol_feed(
              &parser, NULL, 0u, &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_FAULTED);

    header = make_header(JARVIS_SPEECH_MSG_AUDIO, 2u, 1u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    encoded[12] = 1u;
    encoded[13] = 0u;
    encoded[14] = 1u;
    encoded[15] = 0u;
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, encoded, sizeof(encoded), &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_PAYLOAD_LIMIT);

    header = make_header(JARVIS_SPEECH_MSG_HELLO, 1u, 1u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD);
    header = make_header(JARVIS_SPEECH_MSG_AUDIO, 3u, 1u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD);
    header = make_header(99u, 0u, 1u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_HEADER);
    header = make_header(JARVIS_SPEECH_MSG_HELLO, 0u, 0u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_HEADER);
    header = make_header(JARVIS_SPEECH_MSG_HELLO, 0u, 1u);
    memset(header.session_id, 0, sizeof(header.session_id));
    CHECK(jarvis_speech_protocol_encode_header(
              &header, encoded, sizeof(encoded)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_HEADER);
}

static void check_wire_header_rejected(
    const uint8_t encoded[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES]) {
    uint8_t storage[64];
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed = 0u;
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, encoded, JARVIS_SPEECH_PROTOCOL_HEADER_BYTES,
              &consumed, &frame) == JARVIS_SPEECH_PROTOCOL_INVALID_HEADER);
    CHECK(consumed == JARVIS_SPEECH_PROTOCOL_HEADER_BYTES &&
          parser.faulted == 1);
}

static void test_wire_header_rejections(void) {
    uint8_t valid[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    uint8_t mutated[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    JarvisSpeechProtocolHeader header = make_header(
        JARVIS_SPEECH_MSG_HELLO, 0u, 1u);
    CHECK(jarvis_speech_protocol_encode_header(
              &header, valid, sizeof(valid)) == JARVIS_SPEECH_PROTOCOL_OK);

    memcpy(mutated, valid, sizeof(mutated));
    mutated[4] ^= 0x01u;
    check_wire_header_rejected(mutated);

    memcpy(mutated, valid, sizeof(mutated));
    mutated[6] ^= 0x01u;
    check_wire_header_rejected(mutated);

    memcpy(mutated, valid, sizeof(mutated));
    mutated[8] = 99u;
    mutated[9] = 0u;
    check_wire_header_rejected(mutated);

    memcpy(mutated, valid, sizeof(mutated));
    mutated[10] = 1u;
    check_wire_header_rejected(mutated);

    memcpy(mutated, valid, sizeof(mutated));
    memset(mutated + 16u, 0, JARVIS_SPEECH_PROTOCOL_SESSION_BYTES);
    check_wire_header_rejected(mutated);

    memcpy(mutated, valid, sizeof(mutated));
    memset(mutated + 32u, 0, sizeof(uint64_t));
    check_wire_header_rejected(mutated);
}

static void test_invalid_utf8_faults_parser(void) {
    const uint8_t invalid_utf8[] = {0xc0u, 0xafu};
    uint8_t input[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES + sizeof(invalid_utf8)];
    uint8_t storage[16];
    JarvisSpeechProtocolHeader header = make_header(
        JARVIS_SPEECH_MSG_FINAL, (uint32_t)sizeof(invalid_utf8), 1u);
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed;
    CHECK(jarvis_speech_protocol_encode_header(
              &header, input, JARVIS_SPEECH_PROTOCOL_HEADER_BYTES) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    memcpy(input + JARVIS_SPEECH_PROTOCOL_HEADER_BYTES,
           invalid_utf8, sizeof(invalid_utf8));
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, input, sizeof(input), &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD);
    CHECK(consumed == sizeof(input) && parser.faulted == 1);
}

static void test_utf8_validator(void) {
    const uint8_t valid_multibyte[] = {
        0x24u, 0xc2u, 0xa2u, 0xe2u, 0x82u, 0xacu,
        0xf0u, 0x90u, 0x8du, 0x88u
    };
    const uint8_t overlong[] = {0xe0u, 0x80u, 0x80u};
    const uint8_t surrogate[] = {0xedu, 0xa0u, 0x80u};
    const uint8_t too_large[] = {0xf4u, 0x90u, 0x80u, 0x80u};
    const uint8_t embedded_nul[] = {'a', 0u, 'b'};
    CHECK(jarvis_speech_protocol_utf8_valid(NULL, 0u) == 1);
    CHECK(jarvis_speech_protocol_utf8_valid(
              valid_multibyte, sizeof(valid_multibyte)) == 1);
    CHECK(jarvis_speech_protocol_utf8_valid(overlong, sizeof(overlong)) == 0);
    CHECK(jarvis_speech_protocol_utf8_valid(surrogate, sizeof(surrogate)) == 0);
    CHECK(jarvis_speech_protocol_utf8_valid(too_large, sizeof(too_large)) == 0);
    CHECK(jarvis_speech_protocol_utf8_valid(
              embedded_nul, sizeof(embedded_nul)) == 0);
}

static void test_session_and_sequence(void) {
    uint8_t session[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES];
    JarvisSpeechProtocolSequencer sequencer;
    JarvisSpeechProtocolHeader header;
    make_session(session);
    CHECK(jarvis_speech_protocol_sequencer_init(
              &sequencer, session) == JARVIS_SPEECH_PROTOCOL_OK);
    header = make_header(JARVIS_SPEECH_MSG_HELLO, 0u, 1u);
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH);
    header.sequence = 2u;
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_OK);
    header.sequence = 4u;
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH);
    header.sequence = 3u;
    header.session_id[0] ^= 0xffu;
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_SESSION_MISMATCH);
    header.session_id[0] ^= 0xffu;
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_OK);
    sequencer.last_sequence = UINT64_MAX;
    header.sequence = 1u;
    CHECK(jarvis_speech_protocol_sequencer_accept(
              &sequencer, &header) == JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH);
    memset(session, 0, sizeof(session));
    CHECK(jarvis_speech_protocol_sequencer_init(
              &sequencer, session) == JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT);
}

static void test_names_and_arguments(void) {
    uint8_t storage[8];
    JarvisSpeechProtocolParser parser;
    JarvisSpeechProtocolFrame frame;
    size_t consumed = 99u;
    CHECK(strcmp(jarvis_speech_protocol_status_name(
                     JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH),
                 "sequence-mismatch") == 0);
    CHECK(strcmp(jarvis_speech_message_type_name(JARVIS_SPEECH_MSG_START_AUTH),
                 "start-auth") == 0);
    CHECK(strcmp(jarvis_speech_message_type_name(99u), "invalid") == 0);
    CHECK(jarvis_speech_protocol_parser_init(
              &parser, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_OK);
    CHECK(jarvis_speech_protocol_feed(
              &parser, NULL, 1u, &consumed, &frame) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT);
    CHECK(consumed == 0u);
    CHECK(jarvis_speech_protocol_parser_init(
              NULL, storage, sizeof(storage)) ==
          JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT);
}

int main(void) {
    test_fragmented_frame();
    test_coalesced_frames();
    test_invalid_headers_and_limits();
    test_wire_header_rejections();
    test_invalid_utf8_faults_parser();
    test_utf8_validator();
    test_session_and_sequence();
    test_names_and_arguments();
    if (failures != 0) {
        fprintf(stderr, "Speech protocol contract failed: %d/%d checks\n",
                failures, checks);
        return 1;
    }
    printf("Speech protocol contract passed: %d checks\n", checks);
    return 0;
}
