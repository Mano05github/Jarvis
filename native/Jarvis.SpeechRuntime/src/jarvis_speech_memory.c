#include "jarvis_speech_memory.h"

#include <limits.h>
#include <string.h>

int jarvis_speech_checked_add_u64(uint64_t left, uint64_t right, uint64_t *out) {
    if (out == NULL || left > UINT64_MAX - right) return JARVIS_SPEECH_MEMORY_INVALID;
    *out = left + right;
    return JARVIS_SPEECH_MEMORY_OK;
}

int jarvis_speech_checked_mul_u64(uint64_t left, uint64_t right, uint64_t *out) {
    if (out == NULL || (right != 0 && left > UINT64_MAX / right))
        return JARVIS_SPEECH_MEMORY_INVALID;
    *out = left * right;
    return JARVIS_SPEECH_MEMORY_OK;
}

static int valid_kind(JarvisSpeechMemoryKind kind) {
    return kind >= JARVIS_SPEECH_MEM_PERMANENT &&
           kind < JARVIS_SPEECH_MEM_KIND_COUNT;
}

static int valid_phase(JarvisSpeechPhase phase) {
    return phase >= JARVIS_SPEECH_PHASE_LOAD && phase < JARVIS_SPEECH_PHASE_COUNT;
}

void jarvis_speech_memory_init(
    JarvisSpeechMemoryBudget *budget,
    uint64_t private_limit_bytes,
    uint64_t physical_limit_bytes) {
    if (budget == NULL) return;
    memset(budget, 0, sizeof(*budget));
    budget->private_limit_bytes = private_limit_bytes;
    budget->physical_limit_bytes = physical_limit_bytes;
    budget->phase = JARVIS_SPEECH_PHASE_LOAD;
}

static void update_peaks(JarvisSpeechMemoryBudget *budget) {
    const JarvisSpeechPhase phase = budget->phase;
    if (budget->current_private_bytes > budget->peak_private_bytes)
        budget->peak_private_bytes = budget->current_private_bytes;
    if (budget->current_physical_bytes > budget->peak_physical_bytes)
        budget->peak_physical_bytes = budget->current_physical_bytes;
    if (budget->current_private_bytes > budget->peak_private_by_phase[phase])
        budget->peak_private_by_phase[phase] = budget->current_private_bytes;
    if (budget->current_physical_bytes > budget->peak_physical_by_phase[phase])
        budget->peak_physical_by_phase[phase] = budget->current_physical_bytes;
}

int jarvis_speech_memory_set_phase(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechPhase phase) {
    if (budget == NULL || !valid_phase(phase)) return JARVIS_SPEECH_MEMORY_INVALID;
    budget->phase = phase;
    update_peaks(budget);
    return JARVIS_SPEECH_MEMORY_OK;
}

int jarvis_speech_memory_reserve(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechMemoryKind kind,
    uint64_t private_bytes,
    uint64_t physical_bytes) {
    uint64_t next_private;
    uint64_t next_physical;
    uint64_t kind_private;
    uint64_t kind_physical;
    if (budget == NULL || !valid_kind(kind)) return JARVIS_SPEECH_MEMORY_INVALID;
    if (jarvis_speech_checked_add_u64(
            budget->current_private_bytes, private_bytes, &next_private) != 0 ||
        jarvis_speech_checked_add_u64(
            budget->current_physical_bytes, physical_bytes, &next_physical) != 0 ||
        jarvis_speech_checked_add_u64(
            budget->private_by_kind[kind], private_bytes, &kind_private) != 0 ||
        jarvis_speech_checked_add_u64(
            budget->physical_by_kind[kind], physical_bytes, &kind_physical) != 0)
        return JARVIS_SPEECH_MEMORY_INVALID;
    if (next_private > budget->private_limit_bytes ||
        next_physical > budget->physical_limit_bytes)
        return JARVIS_SPEECH_MEMORY_LIMIT;
    budget->current_private_bytes = next_private;
    budget->current_physical_bytes = next_physical;
    budget->private_by_kind[kind] = kind_private;
    budget->physical_by_kind[kind] = kind_physical;
    update_peaks(budget);
    return JARVIS_SPEECH_MEMORY_OK;
}

int jarvis_speech_memory_release(
    JarvisSpeechMemoryBudget *budget,
    JarvisSpeechMemoryKind kind,
    uint64_t private_bytes,
    uint64_t physical_bytes) {
    if (budget == NULL || !valid_kind(kind) ||
        private_bytes > budget->private_by_kind[kind] ||
        physical_bytes > budget->physical_by_kind[kind] ||
        private_bytes > budget->current_private_bytes ||
        physical_bytes > budget->current_physical_bytes)
        return JARVIS_SPEECH_MEMORY_INVALID;
    budget->private_by_kind[kind] -= private_bytes;
    budget->physical_by_kind[kind] -= physical_bytes;
    budget->current_private_bytes -= private_bytes;
    budget->current_physical_bytes -= physical_bytes;
    return JARVIS_SPEECH_MEMORY_OK;
}

uint64_t jarvis_speech_memory_private_available(
    const JarvisSpeechMemoryBudget *budget) {
    if (budget == NULL || budget->current_private_bytes >= budget->private_limit_bytes)
        return 0;
    return budget->private_limit_bytes - budget->current_private_bytes;
}

uint64_t jarvis_speech_memory_physical_available(
    const JarvisSpeechMemoryBudget *budget) {
    if (budget == NULL || budget->current_physical_bytes >= budget->physical_limit_bytes)
        return 0;
    return budget->physical_limit_bytes - budget->current_physical_bytes;
}

static int chunk_bytes(
    const JarvisSpeechChunkCost *cost,
    uint32_t frames,
    uint64_t *private_bytes,
    uint64_t *physical_bytes) {
    uint64_t scaled_private;
    uint64_t scaled_physical;
    if (cost == NULL || private_bytes == NULL || physical_bytes == NULL)
        return JARVIS_SPEECH_MEMORY_INVALID;
    if (jarvis_speech_checked_mul_u64(
            cost->private_bytes_per_frame, frames, &scaled_private) != 0 ||
        jarvis_speech_checked_mul_u64(
            cost->physical_bytes_per_frame, frames, &scaled_physical) != 0 ||
        jarvis_speech_checked_add_u64(
            cost->fixed_private_bytes, scaled_private, private_bytes) != 0 ||
        jarvis_speech_checked_add_u64(
            cost->fixed_physical_bytes, scaled_physical, physical_bytes) != 0)
        return JARVIS_SPEECH_MEMORY_INVALID;
    return JARVIS_SPEECH_MEMORY_OK;
}

static int chunk_fits(
    const JarvisSpeechMemoryBudget *budget,
    const JarvisSpeechChunkCost *cost,
    uint32_t frames,
    uint64_t *private_bytes,
    uint64_t *physical_bytes) {
    if (chunk_bytes(cost, frames, private_bytes, physical_bytes) != 0)
        return JARVIS_SPEECH_MEMORY_INVALID;
    return *private_bytes <= jarvis_speech_memory_private_available(budget) &&
           *physical_bytes <= jarvis_speech_memory_physical_available(budget);
}

int jarvis_speech_plan_chunk(
    const JarvisSpeechMemoryBudget *budget,
    const JarvisSpeechChunkCost *cost,
    uint32_t requested_frames,
    uint32_t minimum_frames,
    JarvisSpeechChunkPlan *out) {
    uint32_t low;
    uint32_t high;
    uint32_t best = 0;
    uint64_t private_bytes = 0;
    uint64_t physical_bytes = 0;
    int fit;
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (budget == NULL || cost == NULL || out == NULL || requested_frames == 0 ||
        minimum_frames == 0 || minimum_frames > requested_frames)
        return JARVIS_SPEECH_MEMORY_INVALID;
    fit = chunk_fits(
        budget, cost, requested_frames, &private_bytes, &physical_bytes);
    if (fit < 0) return JARVIS_SPEECH_MEMORY_INVALID;
    if (fit) {
        out->frames = requested_frames;
        out->additional_private_bytes = private_bytes;
        out->additional_physical_bytes = physical_bytes;
        return JARVIS_SPEECH_MEMORY_OK;
    }
    fit = chunk_fits(budget, cost, minimum_frames, &private_bytes, &physical_bytes);
    if (fit < 0) return JARVIS_SPEECH_MEMORY_INVALID;
    if (!fit) return JARVIS_SPEECH_MEMORY_LIMIT;

    low = minimum_frames;
    high = requested_frames - 1;
    while (low <= high) {
        const uint32_t middle = low + (high - low) / 2;
        fit = chunk_fits(budget, cost, middle, &private_bytes, &physical_bytes);
        if (fit < 0) return JARVIS_SPEECH_MEMORY_INVALID;
        if (fit) {
            best = middle;
            low = middle + 1;
        } else {
            if (middle == 0) break;
            high = middle - 1;
        }
    }
    if (best == 0 || chunk_bytes(cost, best, &private_bytes, &physical_bytes) != 0)
        return JARVIS_SPEECH_MEMORY_INVALID;
    out->frames = best;
    out->additional_private_bytes = private_bytes;
    out->additional_physical_bytes = physical_bytes;
    out->reduced = 1;
    return JARVIS_SPEECH_MEMORY_OK;
}

int jarvis_speech_arena_init(
    JarvisSpeechArena *arena,
    void *buffer,
    size_t capacity) {
    if (arena == NULL || buffer == NULL || capacity == 0)
        return JARVIS_SPEECH_MEMORY_INVALID;
    arena->base = (unsigned char *)buffer;
    arena->capacity = capacity;
    arena->offset = 0;
    arena->peak = 0;
    return JARVIS_SPEECH_MEMORY_OK;
}

void *jarvis_speech_arena_alloc(
    JarvisSpeechArena *arena,
    size_t bytes,
    size_t alignment) {
    uintptr_t address;
    uintptr_t aligned_address;
    uintptr_t base_address;
    size_t aligned;
    size_t mask;
    size_t next;
    if (arena == NULL || arena->base == NULL || bytes == 0 || alignment == 0 ||
        (alignment & (alignment - 1)) != 0)
        return NULL;
    mask = alignment - 1;
    base_address = (uintptr_t)arena->base;
    if (arena->offset > UINTPTR_MAX - base_address) return NULL;
    address = base_address + arena->offset;
    if (address > UINTPTR_MAX - mask) return NULL;
    aligned_address = (address + mask) & ~(uintptr_t)mask;
    if (aligned_address < base_address ||
        aligned_address - base_address > SIZE_MAX)
        return NULL;
    aligned = (size_t)(aligned_address - base_address);
    if (aligned > arena->capacity || bytes > arena->capacity - aligned) return NULL;
    next = aligned + bytes;
    arena->offset = next;
    if (next > arena->peak) arena->peak = next;
    return arena->base + aligned;
}

size_t jarvis_speech_arena_mark(const JarvisSpeechArena *arena) {
    return arena == NULL ? 0 : arena->offset;
}

int jarvis_speech_arena_rewind(JarvisSpeechArena *arena, size_t mark) {
    if (arena == NULL || mark > arena->offset) return JARVIS_SPEECH_MEMORY_INVALID;
    arena->offset = mark;
    return JARVIS_SPEECH_MEMORY_OK;
}

void jarvis_speech_arena_reset(JarvisSpeechArena *arena) {
    if (arena != NULL) arena->offset = 0;
}

const char *jarvis_speech_memory_kind_name(JarvisSpeechMemoryKind kind) {
    static const char *const names[JARVIS_SPEECH_MEM_KIND_COUNT] = {
        "permanent", "mapped-weights", "resident-weights", "audio-ring",
        "feature-ring", "encoder-state", "decoder-state", "workspace", "output"};
    if (!valid_kind(kind)) return "invalid";
    return names[kind];
}

const char *jarvis_speech_phase_name(JarvisSpeechPhase phase) {
    static const char *const names[JARVIS_SPEECH_PHASE_COUNT] = {
        "load", "listen", "encode", "decode"};
    if (!valid_phase(phase)) return "invalid";
    return names[phase];
}
