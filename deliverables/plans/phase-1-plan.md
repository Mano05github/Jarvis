# Jarvis Phase 1 Plan — Foundation, Speech Evidence and Controlled Tanglish Decoding

Status: In progress  
Target duration: four weeks  
Master-plan mapping: S0 Architecture Baseline + S1 Contracts and Identity, with an early isolated speech-certification spike  
Target machine: `mano_pc`, Ryzen 5 7520U, 16 GB RAM, Windows 11 25H2  
Python: 3.12.10 in `D:\Projects\Jarvis\.venv`

## Superseding implementation direction — 12 October 2026

ADR-0007 supersedes the earlier assumption that general owner speech should first be reduced to a bounded deterministic intent registry. The active path is:

`speech → local STT evidence → privacy release → primary multilingual LLM → InteractionEnvelope → deterministic validation → chat/clarify or policy-bound plan → scoped execution → verification → TTS`

The same LLM handles friendly conversation and planning so Jarvis retains one personality and dialogue context. It must return a typed mode, explicitly list assumptions and ask one precise question when consequential information is missing. It cannot invoke tools, approve itself, lower risk, store memory automatically or claim success.

Provider selection is configuration-only. Phase 1 implements Azure OpenAI, OpenAI, Anthropic and local loopback OpenAI-compatible/Ollama/llama.cpp adapters, Windows DPAPI credential references, privacy-aware fallback and provider conformance tests. Live credentials remain owner-supplied and never enter source control.

The deterministic decoder remains a fast-path helper and regression baseline, not a vocabulary ceiling. Qwen3-8B Q4 remains rejected and is not a runtime dependency.

## 1. Phase outcome

Phase 1 establishes a reproducible, testable and security-aware foundation; measures offline STT/TTS; and certifies a provider-neutral primary multilingual LLM gateway for open-domain Tanglish companionship, contextual clarification and typed plan proposal. Deterministic decoding remains an optional helper and benchmark, not a vocabulary ceiling. The rejected Qwen3-8B experiment remains comparison evidence. Phase 1 does not grant Jarvis desktop-control authority.

The phase finishes with:

1. A structured repository and locked Python 3.12.10 environment.
2. Approved architecture decisions, scope, data flows and threat model.
3. Versioned contracts for tasks, speech evidence, semantic packets, intent envelopes, action intents, policy decisions, capability grants, evidence and audit records.
4. A project-local model/data/cache registry that never silently writes large assets outside `D:\Projects\Jarvis\storage`.
5. A repeatable offline STT/TTS benchmark harness and personal Tamil-English evaluation corpus.
6. A certified speech-evidence profile and explicit clarification fallback for `mano_pc`.
7. A certified or rejected controlled Tanglish semantic-decoder profile with accuracy, abstention, latency and memory evidence.
8. A laboratory push-to-talk vertical slice: capture -> VAD/segment -> STT evidence -> semantic decode -> validated intent/clarification -> TTS, with timing and resource telemetry.
9. A Phase 1 evidence report and a go/no-go decision for Phase 2.

## 2. Scope

### Included

- Monorepo structure, developer scripts, configuration and local storage boundaries.
- Python packaging, dependency locking, linting, typing, tests and Windows CI.
- Architecture decision records and threat/data-flow documentation.
- Pydantic contracts and compatibility tests.
- Local model manifests with version, source, license, size and SHA-256.
- Personal speech-corpus format and consent/retention metadata.
- `whisper.cpp` Base Multilingual Q5 and Small Multilingual Q5 benchmarks.
- Challenger STT adapters only when dependencies support Windows/Python 3.12 cleanly.
- Completed Qwen3-8B-Tanglish Q4 GGUF feasibility evaluation through a pinned local runtime and accepted rejection record.
- Compact semantic packets, deterministic Tanglish compilation, evidence validation and simple/complex intent routing.
- Tamil MMS VITS, AI4Bharat Indic-TTS and eSpeak NG fallback evaluation.
- Push-to-talk, lightweight VAD, cancellation and bounded audio buffers.
- CPU, memory, real-time factor, latency, quality and stability reports.

### Explicitly excluded

- Wake-word activation beyond a mock interface.
- Full LangGraph orchestration or persistent personal memory.
- Allowing Qwen or a primary LLM to invoke tools, authorize actions or fabricate missing speech entities.
- Desktop automation, mouse/keyboard control, MCP tools or privileged execution.
- Remote STT/TTS or raw-audio upload.
- Voice cloning, owner impersonation or intentional imitation of an identifiable real
  person or public figure.
- Training or adapting a production voice from copyrighted film/dialogue clips,
  including music-separated derivatives without speaker consent and training rights.
- Production character integration; Phase 1 emits only a stable speech/animation event contract.
- Continuous screen capture, OCR or vision.

## 3. Workstreams and deliverables

### A. Repository and development environment

- Initialize the Git repository and protect local/large/private files with `.gitignore`.
- Create the initial directories: `apps`, `services`, `native`, `src/jarvis`, `benchmarks`, `config`, `policies`, `deliverables`, `tests`, `assets`, `tools` and `scripts`.
- Add `pyproject.toml` with Python `==3.12.*` and separate runtime, benchmark and development dependency groups.
- Produce a deterministic dependency lock and a clean bootstrap command.
- Configure Ruff, mypy, pytest and coverage; add pre-commit checks.
- Add Windows CI for environment creation, static checks, unit tests and package build.
- Verify `scripts/enter-jarvis.ps1` redirects Hugging Face, PyTorch, pip and temporary caches into project storage.

Deliverables: clean bootstrap, dependency lock, CI workflow, contributor/bootstrap guide and environment diagnostic report.

### B. Architecture, scope and security baseline

- Approve ADRs for LangGraph orchestration, local offline speech, Godot character, C# Windows broker, OPA policy, project-local storage and provider-neutral LLM routing.
- Draw context, container and trust-boundary data flows.
- Threat-model microphone data, transcripts, downloaded models, caches, IPC, telemetry and future tool authority.
- Define data classes: PUBLIC, PERSONAL, CONFIDENTIAL, SECRET and PROHIBITED.
- Define Phase 1 retention rules: raw benchmark audio is explicit opt-in; normal microphone audio is not retained.
- Create the initial risk register and acceptance-gate owner/checklist.

Deliverables: ADR set under `deliverables/decisions`, data-flow diagrams, threat model, privacy inventory and risk register.

### C. Contracts and compatibility

- Define versioned Pydantic models for `Task`, `SpeechSegment`, `TranscriptEvent`, `TranscriptEvidence`, `SemanticPacket`, `IntentEnvelope`, `SynthesisRequest`, `PlaybackEvent`, `ActionIntent`, `PolicyDecision`, `Approval`, `CapabilityGrant`, `ToolResult`, `Evidence` and `AuditEvent`.
- Use monotonic timing fields for latency and UUIDs for session/utterance/task correlation.
- Separate untrusted content from instructions and authority fields.
- Generate JSON Schema and golden examples.
- Add backward/forward compatibility and malformed-input tests.
- Define a transport-neutral envelope so named pipes, loopback gRPC or test queues can carry the same events later.

Deliverables: contracts package, generated schemas, examples and compatibility test suite.

### D. Storage and model registry

- Implement one canonical-path resolver rooted at `D:\Projects\Jarvis\storage`.
- Reject traversal, junction escape and accidental writes outside approved storage roots.
- Record model ID, engine, version, quantization, language coverage, source URL, license, size and SHA-256.
- Keep download state separate from certified state.
- Add disk-space preflight, atomic download/finalization and interrupted-download recovery.
- Never commit models, audio, transcripts, caches, secrets or benchmark artifacts.

Deliverables: storage configuration, model manifest schema, integrity verifier and storage safety tests.

### E. Speech benchmark harness

- Provide commands for system inventory, audio-device inventory, corpus validation, STT run, TTS run, comparison and report generation.
- Capture wall time, CPU time, peak working set, model-load time, real-time factor and failures for every run.
- Store machine-readable JSON/JSONL results plus a human-readable Markdown/HTML summary.
- Warm-up engines before measured trials and run at least three measured repetitions.
- Serialize heavy STT/TTS work and record interference from the character/load simulator.
- Preserve engine stdout/stderr in bounded logs with transcript/audio content redacted unless benchmark mode explicitly permits it.

Deliverables: benchmark CLI, adapters, metrics collector, repeatable run manifest and report generator.

### F. Owner speech, Tanglish understanding and dialogue corpora

- Preserve the original 120-prompt acoustic control corpus: 40 Tamil, 40 English and 40 code-switched.
- Treat natural owner Tanglish as primary and the pure-language sets as diagnostic controls.
- Add 40 natural Tanglish owner turns derived from ten original multi-turn scenarios; record the actual words spoken rather than assuming the elicitation example was read exactly.
- Split held-out data by entire scenario so contextual turns cannot leak into development data.
- Maintain a separate, license-reviewed text-variation set for Roman/Tamil-script spelling and code-switch variants.
- Include quiet/near, normal-room and controlled-noise subsets.
- Store speech references, scenario/turn identifiers, language spans, intent/slot labels, referents, policy expectation and consent/retention metadata.
- Evaluate original dialogue acts: command, correction, cancel, confirmation, clarification, completion, status and warning.
- Add an editable English-to-Tamil pronunciation/transliteration dictionary.

Deliverables: versioned speech/dialogue manifests, recording sessions with actual spoken references, held-out scenarios, source/license review and privacy/retention metadata.

### G. STT certification

- Retain generic Whisper Base/Small, Tamil-specialized Whisper, Large-v3-turbo and full Large-v3 as reproducible regression evidence; none is certified to emit authoritative commands.
- Close generic Whisper scaling after full Large-v3 achieved only 1/5 strict semantic success, 0/4 required slots, p95 RTF 12.77 and about 2.15 GiB peak RSS.
- Treat the selected STT profile as an interchangeable producer of untrusted `TranscriptEvidence`, including raw hypotheses, quality signals and evidence-linked entity candidates.
- Measure semantic intent accuracy, slot/entity preservation, cancellation/negation recall and referent resolution as primary quality metrics. Retain WER/CER as diagnostic evidence.
- Test cancellation, empty audio, long pauses, clipped audio, device loss and low-confidence clarification behavior.

Initial certification targets:

- p95 real-time factor no greater than 1.0 on the target CPU.
- p95 final transcript no later than 2.0 seconds after end of speech for normal commands.
- Quiet command exact-match at least 90%; controlled-noise exact-match at least 80%.
- No unbounded memory growth across 100 consecutive utterances.
- STT peak working set target no greater than 2 GB, with the final limit set from evidence.
- The UI/audio loop remains responsive during decoding.

Deliverables: STT comparison report, evidence-producer profile and explicit repeat/typed-input fallback decision.

### H. Deterministic Tanglish semantic decoder

- Normalize only reviewed Tamil-script, Romanized-Tamil and English command vocabulary; preserve unrecognized text rather than guessing a translation.
- Apply explicit precedence for confirmation, correction, commands, cancellation and unknown speech so embedded action words cannot override dialogue state.
- Select slots only from evidence-linked candidates above the score threshold; never manufacture an application, file, reference or policy marker.
- Emit the same compact `SemanticPacket` contract used by model candidates, then expand it through the trusted schema, enum, required-slot and pending-operation gate.
- Return `CLARIFY` for missing or ambiguous critical evidence and `UNKNOWN` for unsupported speech; neither state reaches the primary planner as an executable goal.
- Keep a small classifier optional for measured coverage gaps only. It proposes intent IDs behind the same evidence gate and receives no tool authority.

Certification gates:

- 5/5 strict semantic success on the exact five owner references.
- 100% cancellation and negation preservation.
- Zero fabricated critical entities and zero wrong executable interpretations on corrupted STT.
- 100% schema-valid compact output and no reasoning/prose tokens.
- Stable output across at least 100 repetitions of the complete clean, corrupted-STT and safety suite.
- Measure p50/p95 decode latency, process RSS change and model storage on `mano_pc`.
- Keep the semantic layer model-free unless a future classifier demonstrably improves uncovered-intent accuracy within the existing resource gate.
- Correct interpretation or safe clarification is the end-to-end success metric; WER remains diagnostic.

Deliverables: versioned normalizer/rules, decoder packet/schema, oracle/corrupted-STT/safety report, hardware benchmark and adoption ADR.

Current decision (11 October 2026): Qwen3-8B-Tanglish Q4_K_M is rejected by ADR-0005. The full packet oracle scored 1/5 and the minimal intent/slot ablation scored 4/5; p95 latency remained 35-76 seconds and post-load system headroom remained below 0.7 GiB. The protocol assets are retained for a materially smaller candidate. The failed 8B profile does not advance to corrupted-STT or 100-request testing.

Replacement decision: ADR-0006 adopts the deterministic compiler as the Phase 1 runtime default. It passes all 14 clean/corrupted/safety packets and trusted-gate checks, safely abstains whenever required, needs no model storage and measures 50.2 microseconds p95 on `mano_pc`. A small task-specific classifier is optional only when measured uncovered-intent demand justifies it; it may propose IDs but cannot bypass evidence or policy gates.

### I. TTS certification

- Retain Tamil MMS VITS only as a measured Tamil fallback; owner listening rejected it
  as the primary voice because it does not produce natural Tanglish or the required
  friendly delivery.
- Inspect AI4Bharat IndicF5 and the older AI4Bharat Indic-TTS path for real
  Tamil-English code switching and expressive conditioning before weight acquisition.
- Evaluate an original Tamil cinematic voice direction: warm low register, confident
  energy, friendly precision, subtle contextual wit, crisp consonants, concise
  delivery and natural Tanglish pronunciation, without matching an actor, fictional
  character performance or identifiable person's voice.
- Require documented speaker consent and dataset/model licensing before any custom
  adaptation. Music-separated film audio is reference-only and cannot enter the
  training or speaker-embedding dataset.
- Certify eSpeak NG Tamil as an emergency fallback.
- Measure model-load time, time-to-first-audio, synthesis real-time factor, peak working set, playback underruns and cancellation latency.
- Conduct owner listening scores for clarity, naturalness, consistency and character suitability.
- Add an identity-distinctness review so the accepted voice is recognizably original
  rather than an imitation of the reference speaker.
- Validate chunked synthesis, phrase-cache keys and lip-sync timing/energy events.

Initial certification targets:

- p95 time-to-first-audio no greater than 1.2 seconds for a short response.
- Sustained synthesis real-time factor no greater than 1.0.
- No playback underruns after synthesis begins under the certified load profile.
- Barge-in stops audible playback within 250 ms where the Windows audio stack permits.
- Owner clarity score at least 4/5 for Tamil and 3.5/5 for mixed technical phrases.
- TTS peak working set target no greater than 2 GB, with heavy engines serialized against STT.

Deliverables: voice comparison samples, TTS report and primary/fallback decision.

### J. Laboratory vertical slice

- Start in push-to-talk mode.
- Capture one utterance into a bounded in-memory buffer.
- Run VAD/segmentation and the selected STT evidence producer.
- Display the raw transcript, evidence quality and semantic status without treating model output as authority.
- Run the deterministic Tanglish decoder and validate the resulting `IntentEnvelope`.
- Produce a deterministic acknowledgement or narrow clarification; no Phase 1 tool execution.
- Play audio and emit speech-start, timing/energy, speech-end and cancellation events.
- Record privacy-safe performance telemetry and no raw audio outside explicit benchmark mode.

Deliverables: repeatable demo command, smoke test and captured performance trace.

## 4. Renewed execution order from the current checkpoint

### Direction 1 — Freeze contracts and rubric

- Add `TranscriptEvidence`, compact `SemanticPacket` and expanded `IntentEnvelope` contracts.
- Freeze intent, dialogue-act, marker, reference and clarification codebooks.
- Implement evidence-linked entity candidates and forbid the decoder from selecting anything outside them.
- Encode the Qwen semantic-compiler rubric and grammar as versioned project assets.

Gate: golden clean, ambiguous, corrupted and hostile inputs validate deterministically without loading a model.

### Direction 2 — Close the rejected Qwen experiment

- Resolve the exact Qwen3-8B-Tanglish repository rather than relying on a display name.
- Pin revision, source/base/derivative licenses, data provenance, file inventory and chat template.
- Build or pin `llama.cpp` under `storage/engines/llm` and acquire only the approved Q4 GGUF under `storage/models/llm`.
- Verify hashes, disk placement, no-thinking behavior and project-local caches.

Gate: source/runtime integrity and rejection evidence remain reproducible; rejected weights are not runtime dependencies and may be deleted.

### Direction 3 — Semantic and hardware gate

- Run the five exact owner references without STT to isolate Tanglish understanding.
- Run the five actual Whisper outputs to measure correct recovery versus safe abstention.
- Run spelling, correction, cancellation, confirmation, contextual-reference and prompt-injection cases.
- Measure warm/cold latency, generated tokens, peak RSS, paging, CPU and 100-request stability.
- A/B test compact versus descriptive output only if compact encoding harms correctness.

Gate: all semantic safety targets pass and the laptop remains responsive; otherwise evaluate a smaller decoder.

Status: the 8B candidate failed this gate. The deterministic replacement passed 14/14 cases and is the active Phase 1 route. New classifier work starts only after the registered corpus exposes a measured coverage gap.

### Direction 4 — Intent router and primary-LLM boundary

- Expand valid compact packets into typed `IntentEnvelope` objects.
- Route simple registered intents to deterministic plans; route only complex goals to the primary LLM/LangGraph interface.
- Do not call the primary planner for CLARIFY or UNKNOWN states.
- Constrain primary-LLM output to proposed `ActionIntent`/plan contracts; policy remains a later deterministic authority.

Gate: tests prove neither Qwen nor the primary model can directly invoke a tool or grant authority.

### Direction 5 — Laboratory integration and closeout

- Integrate push-to-talk, STT evidence, semantic decode, clarification and deterministic TTS acknowledgement.
- Revisit capture calibration and select an evidence-producing STT fallback without claiming command certification.
- Complete the TTS comparison and serialize heavy speech/LLM workloads through admission control.
- Publish the Phase 1 evidence report and Phase 2 recommendation.

Gate: the 100-turn laboratory loop remains bounded and every accepted/clarified/unknown result is auditable.

## 5. Phase acceptance criteria

Phase 1 is complete only when:

1. `.venv` reports Python 3.12.10 and dependencies reproduce from the lock.
2. Static checks, unit tests, schema compatibility tests and Windows CI pass.
3. All large files and tool caches remain within `D:\Projects\Jarvis\storage`.
4. No normal-mode microphone recording is retained.
5. Model hashes, versions, sources and licenses are recorded.
6. STT, semantic-decoder and TTS results are repeatable and include latency, quality, CPU and memory evidence.
7. Qwen3-8B is rejected and the deterministic replacement remains certified on the complete Phase 1 semantic gate; no model is accepted merely because it sounds fluent.
8. Every accepted critical slot is bound to supplied evidence; cancellation/negation recall is 100% and fabricated critical entities are zero.
9. Speech-evidence and TTS profiles plus repeat/typed-input fallbacks are selected for the target laptop.
10. The push-to-talk vertical slice survives 100 sequential interactions without leak, deadlock or unbounded growth.
11. Cancellation and device-loss tests recover without restarting the laptop.
12. Threat model, ADRs, risk register and Phase 2 backlog are reviewed.

## 6. Decision defaults

Until changed by the owner, Phase 1 uses natural spoken Tanglish as the primary interaction form, with English and Tamil controls, and evaluates one consistent Tamil-capable Jarvis voice. JARVIS-style behavior means contextual brevity, precise clarification, reasoned status and relevant warnings; it does not mean voice imitation or autonomous authority.

## 7. Phase 2 handoff

Phase 2 begins only after Phase 1 certification. It builds the deterministic control foundation: OPA policy, R0-R4 risk classification, immutable restrictions, trusted approval UI, emergency stop, append-only audit and baseline OpenTelemetry. Production speech integration remains behind these control boundaries.

