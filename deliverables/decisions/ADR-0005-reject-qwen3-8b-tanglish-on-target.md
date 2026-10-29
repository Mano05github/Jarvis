# ADR-0005: Reject Qwen3-8B-Tanglish Q4_K_M on the Phase 1 target

Status: Accepted  
Date: 11 October 2026

## Context

Jarvis needs bounded interpretation of natural Tanglish speech evidence before primary reasoning. The pinned `sugiv/Qwen3-8B-Tanglish` model was converted to a verified 4.682 GiB Q4_K_M GGUF and evaluated locally through pinned llama.cpp on `mano_pc`.

Tokenizer parity passed across the 14-case probe: all 422 token IDs matched between the retained Hugging Face tokenizer with the regex fix and the tokenizer embedded in GGUF. The semantic-packet protocol then achieved 100% JSON, contract and deterministic-gate validity, so remaining errors are not conversion or parser artifacts.

## Evidence

- Full five-case oracle: 1/5 exact, 21.37 s warm p50 and 75.61 s p95.
- Minimal intent/slot ablation: 4/5 exact, 9.51 s warm p50 and 35.24 s p95.
- Confirmation repeatedly became an invented close-app selection and failed the evidence gate, even after one explicit targeted example.
- Resident RSS was approximately 7.0-7.7 GiB; only 0.42-0.65 GiB system memory remained available after load, below the 2 GiB safety floor.
- The candidate therefore fails semantic, latency and resource gates. A 100-request stability run would not change those blocking results and is intentionally skipped.

## Decision

Qwen3-8B-Tanglish Q4_K_M is rejected as a resident Jarvis semantic decoder on the Phase 1 laptop. It receives no tool authority and is not placed in the runtime path.

The grammar, rubric, codebooks, evidence gate and benchmark harness remain model-independent evaluation assets. The next candidate must be materially smaller, must pass the five-case oracle before corrupted-STT or stability testing, and must preserve at least 2 GiB system headroom. Deterministic parsing remains the immediate safe path.

## Consequences

- Do not run further prompt tuning, lower-quality quantization or 100-request testing on this 8B profile.
- Keep the Q4 model only until the decision artifacts are reviewed; it may then be deleted and reacquired from the pinned manifest if needed.
- Evaluate a smaller 1.5B-4B Tanglish-capable decoder or a task-specific classifier under the same evidence-bound protocol.
- Never route a failed or fabricated semantic selection to the primary LLM as an authoritative command.
