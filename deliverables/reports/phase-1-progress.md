# Phase 1 Progress

Updated: 13 October 2026

## Architecture v1.7 update

- Accepted ADR-0007: one primary multilingual LLM now owns open-domain Tanglish companionship, contextual clarification and typed plan proposal behind a provider-neutral gateway.
- Added canonical LLM request/response, interaction, clarification, context, provider, plan and memory-proposal contracts. Plan dependency cycles and contradictory modes are rejected deterministically.
- Added privacy-aware routing: local-only requests and secret/prohibited data cannot fall back to remote providers.
- Added Azure OpenAI, OpenAI-compatible/Ollama/llama.cpp and Anthropic transport adapters with bounded timeouts and normalized failures. Provider responses retain `authority: none`.
- Added secret-free TOML configuration and Windows user-bound DPAPI credential storage plus CLI validation/status commands that do not echo secrets.
- Reclassified the deterministic Tanglish decoder as an optional helper/regression fast path. It is no longer the complete owner-language boundary.
- Qwen3-8B Q4 remains rejected and is not a runtime dependency.
- Live Azure companion/planner smoke certification passed 4/4 cases with 100% schema, mode, authority, script-match and brevity gates; median latency was 2.99 seconds and maximum latency was 3.61 seconds.
- Added a balanced 40-case held-out companion/planner pack: four cases each for companionship, knowledge, correction, anaphora, clarification, cancellation, planning, multi-step planning, ambiguity and prompt injection.
- Strengthened companion evaluation with multi-turn history, exact canonical plan/action checks, clarification-field checks, explicit no-plan gates, known-answer terms, strict script matching and per-category results.
- The initial 40-case live run scored 33/40 raw. Five misses were valid plan-bearing `mixed` envelopes, one was a real ambiguous-target selection and one was an Azure content-filter rejection. Scoring, ambiguity instructions and the synthetic injection case are corrected; a complete revised live regression remains owner-credential gated.
- The revised held-out regression is now certified at 40/40 with all ten categories at 100%, zero provider failures, 3.93-second median latency and 5.83-second maximum latency. The runtime remains simulation-only.
- Added the text-first trusted turn controller with bounded history, expiring clarification continuity, cancellation state transitions and confirmation fail-closed behavior.
- Added deterministic `app.open` compilation for Notepad, Calculator and Visual Studio Code only, plus simulated R0 policy and `would_execute` records. No Windows capability is invoked.
- Added `jarvis text-session`; every session is explicitly simulation-only while the controller and provider behavior are certified.
- Added metadata-only, per-session JSONL audit persistence under project-local storage. Typed event methods exclude prompts, replies, provider errors and credentials; SHA-256 chaining detects modification and reordering.
- Accepted ADR-0008 for privacy-filtered session audit persistence, including the explicit limitation that unsigned local hash chains are not rollback-proof.

## Completed

- Python 3.12.10 virtual environment and version pin
- Canonical project-local large-file storage layout
- Consolidated project documentation under `deliverables`
- Organized assets, generators, plans, checkpoints and manifests
- Python packaging and quality-tool configuration
- Strict task/speech/action/policy/capability/evidence/audit contracts
- Safe storage resolver and model integrity manifest implementation
- Privacy-safe system diagnostics and Phase 1 CLI
- Initial unit/contract tests and Windows CI definition
- Offline workspace/syntax verification
- Deterministic `uv.lock` dependency lock and reproducible environment sync
- Generated versioned JSON Schemas for all service contracts
- Passing Ruff, strict mypy and pytest gates (69 tests, 85.35% coverage)
- Validated speech corpus manifest, recording guide and dependency-light WER/CER metrics
- Bounded speech-engine process supervisor with timeout, process-tree termination and CPU/RAM sampling
- whisper.cpp structured-output adapter and STT JSONL/Markdown benchmark reporting
- Pinned whisper.cpp acquisition/build and local Base/Small Q5_0 model preparation scripts
- Native whisper.cpp CLI and quantizer built successfully from pinned commit; local binary hashes recorded
- Whisper Small Multilingual and locally quantized Small Q5_0 passed an end-to-end offline smoke test
- Small Q5_0 smoke result: 11.0 s audio, 17.08 s elapsed, 1.55 real-time factor and 495,673,344-byte peak RSS
- Model preparation now validates pinned source byte counts and SHA-256 before quantization, uses partial downloads and can quarantine invalid assets
- Repaired Whisper Base source passes its pinned 147,951,465-byte and SHA-256 integrity checks; its Q5_0 model also passes registry and inference validation
- Base Q5_0 smoke result: 11.0 s audio, 4.73 s elapsed, 0.43 real-time factor and 227,028,992-byte peak RSS
- On the common smoke fixture, Base Q5_0 and Small Q5_0 produced identical transcript hashes; accuracy selection still requires the personal Tamil-English corpus
- Generated and validated the canonical 120-utterance corpus manifest: 40 Tamil, 40 English and 40 mixed, with 24 held-out prompts
- Added a dependency-free native Windows corpus recorder with explicit consent flow, resumable sessions, safe non-overwrite defaults and 16 kHz mono PCM validation
- Validated the first five owner recordings; all conform to the required audio format and range from 2.81 to 3.45 seconds
- Five-file cold-process pilot: Base Q5_0 achieved 40% exact match, 0.467 mean WER and 1.28 p95 RTF at about 216 MiB peak RSS
- Five-file cold-process pilot: Small Q5_0 achieved 80% exact match, 0.067 mean WER and 4.87 p95 RTF at about 473 MiB peak RSS
- Benchmark reporting now separates missing/unrecorded corpus audio from genuine engine failures and labels per-utterance process startup measurements explicitly
- Completed all 40 English corpus recordings and the first full English checkpoint
- English cold checkpoint: Base Q5_0 completed 40/40 with 27.5% exact match, 0.648 mean WER and about 218 MiB peak RSS
- English cold checkpoint: Small Q5_0 completed 39/40 with 38.5% exact match, 0.362 mean WER and about 474 MiB peak RSS; one controlled-noise file hit the 120-second guard
- Audio-level audit found no clipping, but speech is too quiet: median RMS is approximately -32 to -34 dBFS and some files fall below -46 dBFS
- Added non-destructive bounded normalization; 40 derived English WAVs now sit near -22 dBFS with zero clipped samples and raw recordings remain unchanged
- Added explicit STT language selection and a loopback-only resident whisper.cpp server adapter with health checking, bounded responses, request timeout, resource sampling and supervised shutdown
- Resident normalized English result for Base Q5_0: 22.5% exact match, 0.504 WER, 1.43 p95 RTF and about 186 MiB peak RSS
- Resident normalized English result for Small Q5_0: 42.5% exact match, 0.294 WER, 5.16 p95 RTF and about 405 MiB peak RSS
- Added per-recording RMS/peak feedback and a low-input warning to prevent under-levelled Tamil and mixed-language capture
- Calibrated Tamil capture now measures -27.3 dBFS median speech-active RMS, -21.1 dBFS active p90, -13.1 dBFS peak and a -63.5 dBFS noise floor; no further microphone boost is needed
- Recorder feedback now uses speech-active 20 ms frame analysis so leading/trailing silence does not trigger false low-level warnings
- Recorded and normalized the first ten Tamil prompts; all peaks are healthy and normalization produced zero clipped samples
- Tamil resident feasibility gate rejects Base Q5_0 (0% exact, 0.885 WER, 2.51 p95 RTF) and Small Q5_0 (0% exact, 0.873 WER, 16.79 p95 RTF)
- Unquantized Small F16 control also failed (0% exact, 0.870 WER, 24.03 p95 RTF, about 707 MiB RSS), proving Q5 quantization is not the material Tamil accuracy cause
- Documented the gated Tamil-specialized challenger order in `deliverables/research/stt-challenger-gate.md`
- Added `scripts/probe-stt-challengers.ps1`, which collects immutable Hugging Face metadata and tests wheel-only Windows/Python 3.12 dependency resolution without installing packages or downloading weights
- TTS corpus/reporting layer and supervised eSpeak NG emergency-fallback adapter
- Added a supervised resident MMS Tamil VITS worker, storage-bound benchmark command,
  balanced 24-prompt Tamil/English/mixed TTS pack and complete-waveform latency/resource
  reporting. Source revision `e9cf59da` is pinned and declares CC-BY-NC-4.0; a
  SafeTensors-only hash-verified acquisition/runtime workflow is ready, model weights
  are acquired and verified. The first real development run completed 12/12 at 1.208
  overall p95 RTF and about 552 MiB peak RSS. Owner listening rejected MMS as primary
  because it speaks pure Tamil and lacks friendly Tanglish delivery; it remains a
  fallback baseline. ADR-0010 and a frozen original voice profile now require
  expressive code-switching, with pinned IndicF5/Indic-TTS source inspection next.
- A strict phonetic-Tanglish MMS stopgap restored reviewed English loanwords and ran
  4/4 at 1.007 p95 RTF, but owner review accepted only 2/4. Mean naturalness was 3.0/5
  and Jarvis fit 3.25/5; conversational delivery remained robotic and command speech
  scored 1/5. The stopgap is rejected and held-out prompts remain sealed.
- Accepted trust-boundary, offline-speech and storage ADRs
- Initial Phase 1 threat model
- Accepted natural Tanglish as the primary interaction form and separated owner speech, text-variation and dialogue evidence
- Added ten original multi-turn scenarios (80 turns) covering context, correction, cancellation, clarification, status and warnings, with scenario-level held-out splitting
- Added a 40-prompt elicited owner-Tanglish v2 manifest model and recorder support for capturing the actual spoken reference
- Completed a license/provenance review of the proposed Tanglish corpora, sentence-embedding model, academic sources and voice-agent stack
- Derived Tamil-dubbed Tony/JARVIS interaction principles without treating copyrighted movie audio or exact dialogue as training data
- Updated the integrated architecture to include dual-script preservation, dialogue state, deterministic parsing, semantic matching and typed local-LLM fallback
- Earlier Tanglish-pilot checkpoint: 110 tests passing with 85.13% coverage
- Added hash-bound recording-session v2 metadata and recoverable WAV revision archiving for future rerecords
- Consolidated the five natural Tanglish recordings into semantic and STT manifests; the stale pre-rerecord `tg_004` observation was rejected by audio statistics
- Added conservative Tanglish normalization, typed dialogue state, turn-bounded pending approvals, deterministic intent/slot/referent parsing and safety-weighted semantic scoring
- Reference-understanding pilot passes 5/5 strict semantic cases
- Generic Whisper Tanglish pilot rejects Base Q5 auto, Small Q5 auto and Small Q5 forced-Tamil: every profile preserves 0/5 semantic intents
- Published `deliverables/reports/tanglish-v2-pilot.md`; the evidence identifies STT, not the deterministic understanding layer, as the current bottleneck
- Downloaded, hash-verified and converted the pinned `vasista22/whisper-tamil-small` source to a 248.2 MB CTranslate2 INT8 model in the project-local Python 3.12.10 runtime
- Added a resident faster-whisper adapter with canonical PCM loading, worker supervision, process-tree resource accounting and failure-gated semantic evaluation
- Added Tamil-script-safe tokenization and conservative dual-script command/safety-marker aliases
- Specialized Tamil Whisper gate: normalized forced-Tamil WER 1.067, p95 RTF 1.80, about 477 MiB RSS, 0/4 required slots and 1/5 strict semantic success
- Auto-language decoding produced the same text at p95 RTF 3.47; domain hotwords worsened WER to 1.325 and strict semantic success to 0/5
- Rejected the Tamil-only fine-tune as primary Jarvis STT and published `deliverables/reports/tanglish-specialized-stt-gate.md`
- Pinned official Whisper Large-v3-turbo revision `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` as the next multilingual/code-switch accuracy-ceiling candidate
- Added metadata-only source inspection, resumable hash-bound SafeTensors acquisition, local CTranslate2 INT8 conversion and an unbiased five-file benchmark workflow for Large-v3-turbo
- Extended the isolated STT worker with beam control, segment confidence evidence and optional word-level timestamps; a real-runtime smoke test confirmed the evidence format and showed word alignment must remain an optional diagnostic
- Large-v3-turbo is rejected: normalized forced-Tamil and auto modes both scored 0/5 strict semantics; forced-Tamil p95 RTF was 7.21 and auto-language p95 RTF was 19.88 at about 1.09 GiB RSS
- Raw forced-Tamil control worsened to 2.497 WER, 8.44 p95 RTF and 0/5 semantics, proving normalization was not the cause
- Pinned official full Whisper Large-v3 revision `06f233fe06e710322aca913c1bc4249a0d71fce1` and added a single-profile accuracy-control workflow
- Full Large-v3 is rejected as a primary command engine: 1/5 strict semantic success, 0/4 required slots, p95 RTF 12.77 and about 2.15 GiB peak RSS
- Closed further generic Whisper scaling and adopted architecture v1.4: STT supplies untrusted evidence, a controlled Qwen3-8B-Tanglish candidate produces compact evidence-bound semantic packets, and deterministic validation routes only accepted complex goals to the primary LLM
- Renewed the Phase 1 plan with Qwen provenance, Q4 GGUF/runtime, oracle/corrupted-STT, abstention, latency, memory and 100-request certification gates
- Implemented frozen `TranscriptEvidence`, compact `SemanticPacket` and authority-free `IntentEnvelope` contracts with exported JSON Schemas
- Added the versioned Qwen semantic-compiler rubric, stable codebooks and compact GBNF grammar under `config/semantic-decoder`
- Added deterministic semantic expansion that rejects unknown intent/reference IDs, unsupplied or wrong-slot candidates, low evidence scores, missing critical markers, confirmation without trusted pending state and missing required slots
- Confirmed exact repository `sugiv/Qwen3-8B-Tanglish` at commit `015825088f2f7bb73fa2ae5efa148365841ebadd`; metadata inspection now passes with Apache-2.0, Qwen3ForCausalLM, documented `sugiv/tanglish-pairs-v1` provenance, no remote code and zero review warnings
- Added a selective Qwen acquisition/conversion workflow that excludes the repository's 27 training checkpoints, pins llama.cpp, verifies the four merged BF16 shards and emits a hash-bound Q4_K_M GGUF manifest
- Added a 14-case resident-server certification harness covering five owner references, five actual corrupted Whisper outputs and four safety cases; it measures output exactness, deterministic-gate validity, safe abstention, cold-load/idle/request RAM, private bytes, system headroom, page-file peaks, warm latency and 100-request RSS drift
- Converted the pinned Qwen candidate to a verified 4.682 GiB Q4_K_M GGUF and built pinned llama.cpp locally
- Verified Hugging Face/GGUF tokenizer parity across the 14-case probe: all 422 token IDs match with the tokenizer regex correction enabled
- Repaired the semantic grammar so ACCEPTED, CLARIFY and UNKNOWN cannot emit contradictory clarification codes; thinking is explicitly disabled and JSON syntax, semantic-contract validity and deterministic-gate validity are measured separately
- Five-case full-packet oracle achieved 100% JSON/contract/gate validity but only 1/5 exact semantics, with 21.37 s p50 and 75.61 s p95 latency
- Minimal intent/slot ablation achieved 4/5 exact; confirmation still fabricated a close-app candidate and was rejected by the evidence gate
- Rejected Qwen3-8B-Tanglish Q4_K_M on `mano_pc`: resident RSS was approximately 7.0-7.7 GiB and only 0.42-0.65 GiB system memory remained after load
- Accepted `ADR-0005`; no 100-request run or further 8B prompt tuning is justified after semantic, latency and memory gates all failed
- Implemented the bounded deterministic Tanglish runtime decoder with dual-script normalization, correction/cancellation/confirmation precedence and evidence-only entity selection
- Added a repeatable deterministic certification CLI and PowerShell entry point covering all clean, real corrupted-STT and safety cases
- Certified the replacement path at 14/14 exact packets, 100% trusted-gate validity, 100% required safe abstention and stable outputs across 1,400 calls
- Measured 28.3 microseconds median and 50.2 microseconds p95 decode latency, zero model bytes and 0.31 MiB process RSS growth on `mano_pc`
- Accepted `ADR-0006`; deterministic decoding is now the Phase 1 default and a small classifier is optional only for uncovered intents
- Current quality gate: 185 tests passing, Ruff clean, strict mypy clean and offline workspace verification clean

## In progress

- Expanding the registered intent/phrase corpus while preserving clarification for missing or ambiguous entities
- Evaluating whether uncovered intent volume justifies a small task-specific classifier behind the same evidence-bound gate
- Implementing the contextual file-workflow laboratory slice without Phase 1 tool authority
- Tamil MMS VITS and AI4Bharat Indic-TTS adapters and measured voice evaluation
- Original consent-cleared Tamil cinematic voice design and identity-distinctness
  evaluation; public-figure/movie audio remains reference-only, never training data

## External prerequisite

The machine has the .NET runtime but no .NET SDK. Install the .NET 8 SDK before the S1 named-pipe identity prototype. Generic Whisper Base/Small remain baselines and have not passed the Tamil gate. AI4Bharat IndicConformer is deferred because its gated source and native NeMo dependency chain do not pass the Windows/Python 3.12 Phase 1 gate. Final speech certification requires natural Tanglish recordings and a viable Tamil/code-switch challenger.

