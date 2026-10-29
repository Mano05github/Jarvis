#ifndef JARVIS_SPEECH_PROTOCOL_H
#define JARVIS_SPEECH_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define JARVIS_SPEECH_PROTOCOL_MAGIC 0x5454534Au
#define JARVIS_SPEECH_PROTOCOL_VERSION 1u
#define JARVIS_SPEECH_PROTOCOL_HEADER_BYTES 40u
#define JARVIS_SPEECH_PROTOCOL_SESSION_BYTES 16u
#define JARVIS_SPEECH_PROTOCOL_MAX_PAYLOAD_BYTES 65536u
#define JARVIS_SPEECH_PROTOCOL_MAX_AUDIO_BYTES 32768u
#define JARVIS_SPEECH_PROTOCOL_MAX_TEXT_BYTES 8192u
#define JARVIS_SPEECH_PROTOCOL_MAX_CONTROL_BYTES 4096u
#define JARVIS_SPEECH_PROTOCOL_BOOTSTRAP_BYTES 40u
#define JARVIS_SPEECH_PROTOCOL_AUTH_DIGEST_BYTES 32u
#define JARVIS_SPEECH_PROTOCOL_AUTH_LABEL "jarvis-stt-start-auth-v1"

#define JARVIS_SPEECH_WORKER_CAP_FAKE_BACKEND (1u << 0)
#define JARVIS_SPEECH_WORKER_CAP_AUTH_CHALLENGE (1u << 1)

typedef enum JarvisSpeechProtocolStatus {
    JARVIS_SPEECH_PROTOCOL_OK = 0,
    JARVIS_SPEECH_PROTOCOL_NEED_MORE = 1,
    JARVIS_SPEECH_PROTOCOL_FRAME_READY = 2,
    JARVIS_SPEECH_PROTOCOL_INVALID_ARGUMENT = -1,
    JARVIS_SPEECH_PROTOCOL_INVALID_HEADER = -2,
    JARVIS_SPEECH_PROTOCOL_PAYLOAD_LIMIT = -3,
    JARVIS_SPEECH_PROTOCOL_INVALID_PAYLOAD = -4,
    JARVIS_SPEECH_PROTOCOL_SESSION_MISMATCH = -5,
    JARVIS_SPEECH_PROTOCOL_SEQUENCE_MISMATCH = -6,
    JARVIS_SPEECH_PROTOCOL_FAULTED = -7
} JarvisSpeechProtocolStatus;

typedef enum JarvisSpeechMessageType {
    JARVIS_SPEECH_MSG_HELLO = 1,
    JARVIS_SPEECH_MSG_BOOTSTRAP = 2,
    JARVIS_SPEECH_MSG_START_AUTH = 3,
    JARVIS_SPEECH_MSG_READY = 4,
    JARVIS_SPEECH_MSG_START_SESSION = 5,
    JARVIS_SPEECH_MSG_AUDIO = 6,
    JARVIS_SPEECH_MSG_PARTIAL = 7,
    JARVIS_SPEECH_MSG_FINISH = 8,
    JARVIS_SPEECH_MSG_FINAL = 9,
    JARVIS_SPEECH_MSG_CANCEL = 10,
    JARVIS_SPEECH_MSG_RESET = 11,
    JARVIS_SPEECH_MSG_STATS = 12,
    JARVIS_SPEECH_MSG_ERROR = 13,
    JARVIS_SPEECH_MSG_SHUTDOWN = 14
} JarvisSpeechMessageType;

typedef struct JarvisSpeechProtocolHeader {
    uint16_t message_type;
    uint16_t flags;
    uint32_t payload_bytes;
    uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES];
    uint64_t sequence;
} JarvisSpeechProtocolHeader;

typedef struct JarvisSpeechProtocolFrame {
    JarvisSpeechProtocolHeader header;
    /* Valid until the next call to jarvis_speech_protocol_feed(). */
    const uint8_t *payload;
} JarvisSpeechProtocolFrame;

typedef struct JarvisSpeechProtocolParser {
    uint8_t header_buffer[JARVIS_SPEECH_PROTOCOL_HEADER_BYTES];
    size_t header_used;
    uint8_t *payload_buffer;
    size_t payload_capacity;
    size_t payload_used;
    JarvisSpeechProtocolHeader current_header;
    int header_decoded;
    int faulted;
} JarvisSpeechProtocolParser;

typedef struct JarvisSpeechProtocolSequencer {
    uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES];
    uint64_t last_sequence;
    int initialized;
} JarvisSpeechProtocolSequencer;

int jarvis_speech_protocol_parser_init(
    JarvisSpeechProtocolParser *parser,
    void *payload_buffer,
    size_t payload_capacity);
/* Returns NEED_MORE, FRAME_READY, or a negative error. */
int jarvis_speech_protocol_feed(
    JarvisSpeechProtocolParser *parser,
    const void *data,
    size_t data_bytes,
    size_t *consumed_bytes,
    JarvisSpeechProtocolFrame *out_frame);

int jarvis_speech_protocol_encode_header(
    const JarvisSpeechProtocolHeader *header,
    void *output,
    size_t output_capacity);
int jarvis_speech_protocol_validate_header(
    const JarvisSpeechProtocolHeader *header,
    size_t payload_capacity);
int jarvis_speech_protocol_utf8_valid(const void *data, size_t data_bytes);

int jarvis_speech_protocol_sequencer_init(
    JarvisSpeechProtocolSequencer *sequencer,
    const uint8_t session_id[JARVIS_SPEECH_PROTOCOL_SESSION_BYTES]);
int jarvis_speech_protocol_sequencer_accept(
    JarvisSpeechProtocolSequencer *sequencer,
    const JarvisSpeechProtocolHeader *header);

const char *jarvis_speech_protocol_status_name(int status);
const char *jarvis_speech_message_type_name(uint16_t message_type);

#ifdef __cplusplus
}
#endif

#endif
