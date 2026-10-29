#include "jarvis_speech_memory.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MIB ((uint64_t)1024 * 1024)

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

static void test_checked_arithmetic(void) {
    uint64_t value = 0;
    CHECK(jarvis_speech_checked_add_u64(2, 3, &value) == 0 && value == 5);
    CHECK(jarvis_speech_checked_add_u64(UINT64_MAX, 1, &value) == -1);
    CHECK(jarvis_speech_checked_mul_u64(4, 5, &value) == 0 && value == 20);
    CHECK(jarvis_speech_checked_mul_u64(UINT64_MAX, 2, &value) == -1);
    CHECK(jarvis_speech_checked_add_u64(1, 1, NULL) == -1);
}

static void test_budget_and_phase_peaks(void) {
    JarvisSpeechMemoryBudget budget;
    jarvis_speech_memory_init(&budget, 512 * MIB, 768 * MIB);
    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_MAPPED_WEIGHTS, 0, 300 * MIB) == 0);
    CHECK(budget.current_private_bytes == 0);
    CHECK(budget.current_physical_bytes == 300 * MIB);
    CHECK(jarvis_speech_memory_set_phase(&budget, JARVIS_SPEECH_PHASE_ENCODE) == 0);
    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_WORKSPACE, 128 * MIB, 160 * MIB) == 0);
    CHECK(budget.peak_private_by_phase[JARVIS_SPEECH_PHASE_ENCODE] == 128 * MIB);
    CHECK(budget.peak_physical_by_phase[JARVIS_SPEECH_PHASE_ENCODE] == 460 * MIB);
    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_OUTPUT, 400 * MIB, 400 * MIB) == 1);
    CHECK(budget.current_private_bytes == 128 * MIB);
    CHECK(jarvis_speech_memory_release(
              &budget, JARVIS_SPEECH_MEM_WORKSPACE, 128 * MIB, 160 * MIB) == 0);
    CHECK(jarvis_speech_memory_release(
              &budget, JARVIS_SPEECH_MEM_WORKSPACE, 1, 0) == -1);
    CHECK(jarvis_speech_memory_private_available(&budget) == 512 * MIB);
    CHECK(jarvis_speech_memory_physical_available(&budget) == 468 * MIB);
}

static void test_chunk_planning(void) {
    JarvisSpeechMemoryBudget budget;
    JarvisSpeechChunkCost cost;
    JarvisSpeechChunkPlan plan;
    jarvis_speech_memory_init(&budget, 1000, 1000);
    memset(&cost, 0, sizeof(cost));
    cost.fixed_private_bytes = 100;
    cost.fixed_physical_bytes = 200;
    cost.private_bytes_per_frame = 10;
    cost.physical_bytes_per_frame = 20;

    CHECK(jarvis_speech_plan_chunk(&budget, &cost, 20, 1, &plan) == 0);
    CHECK(plan.frames == 20 && plan.reduced == 0);
    CHECK(plan.additional_private_bytes == 300);
    CHECK(plan.additional_physical_bytes == 600);

    CHECK(jarvis_speech_memory_reserve(
              &budget, JARVIS_SPEECH_MEM_PERMANENT, 500, 500) == 0);
    CHECK(jarvis_speech_plan_chunk(&budget, &cost, 20, 1, &plan) == 0);
    CHECK(plan.frames == 15 && plan.reduced == 1);
    CHECK(plan.additional_private_bytes == 250);
    CHECK(plan.additional_physical_bytes == 500);
    CHECK(budget.current_private_bytes == 500 && budget.current_physical_bytes == 500);

    CHECK(jarvis_speech_plan_chunk(&budget, &cost, 20, 16, &plan) == 1);
    CHECK(plan.frames == 0);
    cost.private_bytes_per_frame = UINT64_MAX;
    CHECK(jarvis_speech_plan_chunk(&budget, &cost, 2, 1, &plan) == -1);
}

static void test_fixed_arena(void) {
    unsigned char storage[128];
    JarvisSpeechArena arena;
    void *first;
    void *second;
    size_t mark;
    memset(storage, 0, sizeof(storage));
    CHECK(jarvis_speech_arena_init(&arena, storage, sizeof(storage)) == 0);
    first = jarvis_speech_arena_alloc(&arena, 3, 1);
    mark = jarvis_speech_arena_mark(&arena);
    second = jarvis_speech_arena_alloc(&arena, 16, 16);
    CHECK(first == storage);
    CHECK(second != NULL && ((uintptr_t)second % 16) == 0);
    CHECK(arena.peak >= 16);
    CHECK(jarvis_speech_arena_alloc(&arena, 200, 1) == NULL);
    CHECK(jarvis_speech_arena_alloc(&arena, 1, 3) == NULL);
    CHECK(jarvis_speech_arena_rewind(&arena, mark) == 0);
    CHECK(arena.offset == mark);
    CHECK(jarvis_speech_arena_rewind(&arena, 129) == -1);
    jarvis_speech_arena_reset(&arena);
    CHECK(arena.offset == 0 && arena.peak > 0);
}

static void test_names_and_invalid_inputs(void) {
    JarvisSpeechMemoryBudget budget;
    jarvis_speech_memory_init(&budget, 10, 10);
    CHECK(strcmp(jarvis_speech_memory_kind_name(JARVIS_SPEECH_MEM_AUDIO_RING),
                 "audio-ring") == 0);
    CHECK(strcmp(jarvis_speech_memory_kind_name(JARVIS_SPEECH_MEM_KIND_COUNT),
                 "invalid") == 0);
    CHECK(strcmp(jarvis_speech_phase_name(JARVIS_SPEECH_PHASE_DECODE),
                 "decode") == 0);
    CHECK(jarvis_speech_memory_set_phase(&budget, JARVIS_SPEECH_PHASE_COUNT) == -1);
    CHECK(jarvis_speech_memory_reserve(
              NULL, JARVIS_SPEECH_MEM_PERMANENT, 1, 1) == -1);
    CHECK(jarvis_speech_memory_private_available(NULL) == 0);
}

int main(void) {
    test_checked_arithmetic();
    test_budget_and_phase_peaks();
    test_chunk_planning();
    test_fixed_arena();
    test_names_and_invalid_inputs();
    if (failures != 0) {
        fprintf(stderr, "Speech memory contract failed: %d/%d checks\n", failures, checks);
        return 1;
    }
    printf("Speech memory contract passed: %d checks\n", checks);
    return 0;
}
