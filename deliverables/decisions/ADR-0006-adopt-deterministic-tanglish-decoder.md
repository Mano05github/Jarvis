# ADR-0006: Adopt the deterministic Tanglish decoder for Phase 1

Status: Accepted  
Date: 11 October 2026

## Context

ADR-0005 rejected Qwen3-8B-Tanglish Q4_K_M because it failed semantic accuracy, latency and memory gates on `mano_pc`. Jarvis still needs a low-latency way to preserve Tanglish dialogue acts, critical markers, references and evidence-linked entities before primary reasoning.

## Evidence

- Five clean owner commands, five actual corrupted-Whisper transcripts and four ambiguity/injection safety cases were frozen as the Phase 1 packet gate.
- The deterministic compiler matched all 14 expected compact packets and all 14 passed trusted semantic expansion.
- Required safe abstention was 100%; missing and ambiguous targets never fabricate a candidate.
- Outputs stayed stable across 100 repetitions of the complete suite (1,400 decoder calls).
- On `mano_pc`, median decode latency was 28.3 microseconds, p95 was 50.2 microseconds, model storage was zero bytes and observed process RSS growth was 327,680 bytes.

## Decision

Use the bounded deterministic Tanglish compiler as the Phase 1 default semantic-decoding path. It normalizes only reviewed Tamil-script, Romanized-Tamil and English control vocabulary; applies explicit dialogue-act precedence; and selects only supplied evidence candidates above the trusted threshold.

Unsupported, incomplete or ambiguous input returns `CLARIFY` or `UNKNOWN`. Accepted typed envelopes may be routed to deterministic handlers or, for genuinely complex goals, to the primary LLM for planning. Neither path gains tool authority from semantic decoding.

## Consequences

- The rejected Qwen Q4 model is not a runtime dependency and may be deleted.
- Expand coverage through versioned phrase/intent registries and owner-derived tests rather than unconstrained prompting.
- Consider a small task-specific classifier only after measured coverage gaps justify it. Its output remains a proposal behind the existing candidate, schema, required-slot and policy gates.
- Keep Qwen rubric, grammar and benchmark evidence as reusable evaluation assets, not production dependencies.
