#ifndef JARVIS_SPEECH_MEMORY_H
#define JARVIS_SPEECH_MEMORY_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum JarvisSpeechMemoryStatus {
    JARVIS_SPEECH_MEMORY_OK = 0,
    JARVIS_SPEECH_MEMORY_LIMIT = 1,
    JARVIS_SPEECH_MEMORY_INVALID = -1
} JarvisSpeechMemoryStatus;

typedef enum JarvisSpeechMemoryKind {
    JARVIS_SPEECH_MEM_PERMANENT = 0,
    JARVIS_SPEECH_MEM_MAPPED_WEIGHTS,
    JARVIS_SPEECH_MEM_RESIDENT_WEIGHTS,
    JARVIS_SPEECH_MEM_AUDIO_RING,
    JARVIS_SPEECH_MEM_FEATURE_RING,
    JARVIS_SPEECH_MEM_ENCODER_STATE,
    JARVIS_SPEECH_MEM_DECODER_STATE,
    JARVIS_SPEECH_MEM_WORKSPACE,
    JARVIS_SPEECH_MEM_OUTPUT,
    JARVIS_SPEECH_MEM_KIND_COUNT
} JarvisSpeechMemoryKind;

typedef enum JarvisSpeechPhase {
    JARVIS_SPEECH_PHASE_LOAD = 0,
    JARVIS_SPEECH_PHASE_LISTEN,
    JARVIS_SPEECH_PHASE_ENCODE,
    JARVIS_SPEECH_PHASE_DECODE,
    JARVIS_SPEECH_PHASE_COUNT
} JarvisSpeechPhase;

typedef struct JarvisSpeechMemoryBudget {
    uint64_t private_limit_bytes;
    uint64_t physical_limit_bytes;
    uint64_t current_private_bytes;
    uint64_t current_physical_bytes;
    uint64_t peak_private_bytes;
    uint64_t peak_physical_bytes;
    uint64_t private_by_kind[JARVIS_SPEECH_MEM_KIND_COUNT];
    uint64_t physical_by_kind[JARVIS_SPEECH_MEM_KIND_COUNT];
    uint64_t peak_private_by_phase[JARVIS_SPEECH_PHASE_COUNT];
    uint64_t peak_physical_by_phase[JARVIS_SPEECH_PHASE_COUNT];
    JarvisSpeechPhase phase;
} JarvisSpeechMemoryBudget;

typedef struct JarvisSpeechChunkCost {
    uint64_t fixed_private_bytes;
    uint64_t fixed_physical_bytes;
    uint64_t private_bytes_per_frame;
    uint64_t physical_bytes_per_frame;
} JarvisSpeechChunkCost;

typedef struct JarvisSpeechChunkPlan {
    uint32_t frames;
    uint64_t additional_private_bytes;
    uint64_t additional_physical_bytes;
    int reduced;
} JarvisSpeechChunkPlan;

typedef struct JarvisSpeechArena {
    unsigned char *base;
    size_t capacity;
    size_t offset;
    size_t peak;
} JarvisSpeechArena;

int jarvis_speech_checked_add_u64(uint64_t left, uint64_t right, uint64_t *out);
int jarvis_speech_checked_mul_u64(uint64_t left, uint64_t right, uint64_t *out);

void jarvis_speech_memory_init(
    JarvisSpeechMemoryBudget *budget,
    uint64_t private_limit_bytes,
    uint64_t physical_limit_bytes);
int jarvis_speech_memory_set_phase(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechPhase phase);
int jarvis_speech_memory_reserve(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechMemoryKind kind,
    uint64_t private_bytes,
    uint64_t physical_bytes);
int jarvis_speech_memory_release(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechMemoryKind kind,
    uint64_t private_bytes,
    uint64_t physical_bytes);
uint64_t jarvis_speech_memory_private_available(
    const JarvisSpeechMemoryBudget *budget);
uint64_t jarvis_speech_memory_physical_available(
    const JarvisSpeechMemoryBudget *budget);

int jarvis_speech_plan_chunk(
    const JarvisSpeechMemoryBudget *budget,
    const JarvisSpeechChunkCost *cost,
    uint32_t requested_frames,
    uint32_t minimum_frames,
    JarvisSpeechChunkPlan *out);

int jarvis_speech_arena_init(
    JarvisSpeechArena *arena,
    void *buffer,
    size_t capacity);
void *jarvis_speech_arena_alloc(
    JarvisSpeechArena *arena,
    size_t bytes,
    size_t alignment);
size_t jarvis_speech_arena_mark(const JarvisSpeechArena *arena);
int jarvis_speech_arena_rewind(JarvisSpeechArena *arena, size_t mark);
void jarvis_speech_arena_reset(JarvisSpeechArena *arena);

const char *jarvis_speech_memory_kind_name(JarvisSpeechMemoryKind kind);
const char *jarvis_speech_phase_name(JarvisSpeechPhase phase);

#ifdef __cplusplus
}
#endif

#endif
