# Jarvis session checkpoint

## Active resume checkpoint — 13 October 2026

This section supersedes the older historical checkpoint below.

### Current architecture

- Architecture baseline is v1.7. The updated master document is `deliverables/architecture/Jarvis_Architecture_and_Implementation_Plan.docx`.
- Natural open-domain Tanglish, English and Tamil go from local STT evidence directly to one configurable primary multilingual LLM.
- That primary LLM handles companionship, questions, contextual clarification and typed plan proposals. It never receives tool or authorization authority.
- Trusted flow: `speech/text → context/privacy release → primary LLM → InteractionEnvelope validation → chat/clarify or plan compilation → policy/approval → scoped tool → verification → TTS`.
- The deterministic Tanglish decoder is only an optional fast-path helper, safety-marker detector and regression baseline. It is not a vocabulary ceiling.
- Qwen3-8B-Tanglish Q4_K_M is rejected for quality, RAM and latency and is not a runtime dependency.
- ADR-0007 is the current language/cognition decision; it supersedes ADR-0006 only where ADR-0006 made deterministic decoding the general default route.

### Provider configuration

- Active local configuration: `config/llm-providers.local.toml` (Git-ignored).
- Active profile: Azure OpenAI deployment `gpt-5.6-sol` through the owner-configured endpoint and API version.
- The API key is not in TOML. It is stored as Windows user-bound DPAPI data under `storage/secrets/llm`, referenced by `jarvis/llm/azure-primary`.
- DPAPI secrets must be used from the owner's PowerShell identity. The managed Codex execution identity can see the blob but cannot decrypt it; this is expected.
- Provider-neutral adapters now exist for Azure OpenAI, OpenAI, Anthropic and loopback OpenAI-compatible/Ollama/llama.cpp endpoints.
- Remote fallback is privacy-aware: local-only requests and SECRET/PROHIBITED data cannot use a remote provider.

### Live LLM evidence

- Live Azure companion/planner smoke suite passed 4/4 cases.
- Certified gates: 100% interaction-mode accuracy, authority isolation, Romanized-script matching and brevity.
- Median latency: 2.99 seconds; maximum latency: 3.61 seconds.
- Tested modes: friendly chat, missing-target clarification, Notepad plan proposal and cancellation.
- Example plan was correctly typed as `app.open` with `application=Notepad` and `authority=none`.
- The live interactive text session also passed a natural multi-turn Tanglish conversation. It maintained context, used an appropriate companion tone and refused to state an unverified current political claim as fact.

### Implemented trusted runtime

- `src/jarvis/runtime/conversation.py` implements bounded multi-turn history, expiring clarification state, clarification resumption, unrelated-chat preservation, cancellation and confirmation fail-closed behavior.
- Clarification answers that resolve to `no_action`, plus plans rejected by the trusted compiler, now consume stale clarification state. Unrelated `chat` and `answer` turns continue to preserve it.
- `src/jarvis/runtime/actions.py` deterministically compiles only `app.open` for Notepad, Calculator and Visual Studio Code.
- Unknown actions, applications and extra arguments are rejected before policy.
- `SimulatedPolicyGateway` classifies registered launches as R0, and `SimulationExecutor` emits only `would_execute` records. It cannot touch Windows.
- `jarvis text-session --config config/llm-providers.local.toml` starts the interactive companion loop. It is explicitly simulation-only.
- Interactive text sessions now persist metadata-only, per-session hash-chained JSONL audit events under `storage/audit/sessions`. Prompts, replies, system instructions, provider errors, credential references and secret values have no audit-writer input path.
- Audit events cover session start/close, turn start/completion/failure and canonical simulated-action outcomes. Existing chains are verified before append and each event is flushed to disk.
- ADR-0008 records the boundary: local SHA-256 chains are tamper-evident but are not yet signed or rollback-proof.
- `config/llm/companion-eval-heldout-v1.jsonl` now contains 40 balanced synthetic held-out cases across companionship, knowledge, correction, anaphora, clarification, cancellation, planning, multi-step planning, ambiguity and prompt injection.
- The live evaluator now checks multi-turn history, canonical plan actions/arguments, clarification fields, no-plan guarantees, known-answer terms, script matching, brevity, authority isolation and per-category accuracy.
- The initial 40-case live run completed at a raw 33/40 (82.5%). Adjudication found five evaluator false negatives where `mixed` contained the exact expected plan, one genuine ambiguous-target failure and one Azure `content_filter` rejection. Returned-envelope behavior was 38/39 (97.4%) after adjudication; this is not final certification.
- Plan-bearing `mixed` scoring is corrected, the rubric now forbids choosing among unspecified alternative action targets, and the filter-triggering injection case is reframed as untrusted quoted content without weakening its no-plan requirement. The initial evidence and limitations are recorded in `deliverables/reports/companion-heldout-v1-initial.md`.
- The revised live run reached 39/40 with zero provider failures and 100% in every category except correction. The remaining miss was safe over-clarification: `Notepad illa, VS Code` was treated as alternatives rather than a contextual correction. The rubric now distinguishes correction markers from unresolved alternatives, and the CLI supports repeatable validated `--case-id` selection.
- The targeted correction retest passed 1/1, followed by final live certification at 40/40: every category reached 100%, authority and mode accuracy were 100%, provider failures were zero, median latency was 3.93 seconds and maximum latency was 5.83 seconds. Evidence is under `storage/benchmarks/results/llm-companion-20261013T143522Z`.
- Voice direction is now governed by ADR-0009: Jarvis may use an original consent-cleared Tamil cinematic voice with a warm low register, confident energy and crisp Tanglish delivery, but not Vijay's identifiable voice or another real-person imitation. The supplied music-backed film clip is reference-only and cannot enter training or speaker-embedding data.
- TTS prototype slice includes a resident offline MMS VITS worker, a storage-bound benchmark CLI, complete-waveform latency/resource reporting, a balanced 24-prompt original Tamil/English/mixed evaluation pack and a hash-bound acquisition workflow. MMS source revision `e9cf59da` declares CC-BY-NC-4.0. The real development run completed 12/12 at 1.208 overall p95 RTF and about 552 MiB peak RSS, but owner listening rejected it as the primary voice because it speaks pure Tamil and lacks the required friendly Tanglish delivery. It remains only a Tamil fallback/baseline. ADR-0010 requires an original expressive code-switch voice; IndicF5 and Indic-TTS source revisions are pinned for inspection. No film/public-figure/actor audio is used.
- Current quality state: 188 tests passing; Ruff clean; strict mypy clean; offline workspace verification passing.

### Last successful manual interaction

The owner ran `text-session` and held a natural Tanglish conversation covering boredom, Vijay's political entry and an asserted current-election result. Jarvis preserved conversation context and correctly asked for an official source rather than fabricating current information. The action-session gate is also complete: registered `app.open` requests emitted only `would_execute`, unsupported `app.close` failed closed without stale state, clarification resumed into a Calculator simulation, and cancellation of a genuine pending clarification cleared it. `/state` verified `pending_dialogue_id: null` after both terminal paths.

### Exact next development sequence

1. MMS phonetic-Tanglish owner review is complete and rejected: 2/4 accepted, mean intelligibility/pronunciation 3.5/5, naturalness 3.0/5 and Jarvis fit 3.25/5. Conversation remained robotic and command speech scored 1/5. Keep held-out prompts sealed.
2. Obtain owner direction on secure read-only Hugging Face authentication for metadata-only Indic Parler-TTS inspection versus remaining anonymous and moving to a consent-cleared custom voice/training path. Never paste a token into chat or store it in the project.
3. Add a simulated approval state for R1+ plans; confirmation must bind to an exact pending digest and expiry.
4. Connect `app.open` to the signed/narrow Windows broker only after its own gates pass. Do not call `Start-Process` directly from the model/controller.
5. Connect local STT transcripts to the same turn controller, then integrate the certified original TTS voice, pronunciation dictionary and barge-in.

### Useful commands

```powershell
.\.venv\Scripts\python.exe -m jarvis llm-secret-status --reference jarvis/llm/azure-primary

.\.venv\Scripts\python.exe -m jarvis llm-companion-evaluate `
  --config config\llm-providers.local.toml `
  --cases config\llm\companion-eval-smoke-v1.jsonl `
  --rubric config\llm\companion-planner-rubric-v1.txt

.\.venv\Scripts\python.exe -m jarvis llm-companion-evaluate `
  --config config\llm-providers.local.toml `
  --cases config\llm\companion-eval-heldout-v1.jsonl `
  --rubric config\llm\companion-planner-rubric-v1.txt

.\.venv\Scripts\python.exe -m jarvis text-session `
  --config config\llm-providers.local.toml

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe tools\verify_workspace.py
```

## Historical checkpoint — 10 October 2026

Updated: 10 October 2026

## Current state

- The Jarvis reference architecture, Tool Capability Platform, guardrail architecture, failure control plane, progress/status system, OpenTelemetry strategy, character specification and implementation plan have been designed.
- The main architecture document is `deliverables/architecture/Jarvis_Architecture_and_Implementation_Plan.docx`.
- The corrected sprint workbook is `deliverables/plans/Jarvis_Implementation_Sprint_Plan_v2.xlsx`.
- Both Office documents pass Microsoft's strict OpenXML validator.
- Architecture baseline v1.2 adds separate STT/TTS architectures plus natural Tanglish, dialogue state, layered understanding and the final integrated architecture.
- Project virtual environment: `D:\Projects\Jarvis\.venv` using Python 3.12.10; pinned by `.python-version`.
- Canonical large-file root: `D:\Projects\Jarvis\storage` for engines, models, datasets, caches, benchmark outputs and temporary files.
- Phase 1 execution plan: `deliverables/plans/phase-1-plan.md`.
- Project documentation is consolidated under `deliverables`; the separate `docs` directory has been retired.
- Phase 1 foundation implementation is in progress: packaging, contracts, safe storage, model integrity, diagnostics, corpus validation, accuracy metrics, tests, CI, ADRs and threat modeling are scaffolded.
- Speech benchmarking now includes bounded process supervision, whisper.cpp STT and eSpeak NG TTS adapters, JSONL/Markdown reporting, and pinned acquisition/quantization scripts.
- Native `whisper-cli.exe` and `whisper-quantize.exe` are built from pinned commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`; their sizes and SHA-256 values are stored in the project-local engine manifest.
- Whisper Base and Small Q5_0 pass registry integrity checks and end-to-end offline inference.
- Base Q5_0 measured 0.43 real-time factor and about 217 MiB peak RSS on the bundled 11-second fixture. It is the provisional real-time profile.
- Small Q5_0 measured 1.55 real-time factor and about 473 MiB peak RSS on the same fixture. It remains the accuracy challenger but currently misses the 1.0 real-time-factor target.
- Both models produced the same transcript hash on the fixture; the personal Tamil-English corpus must decide accuracy.
- The validated corpus manifest is `storage/datasets/speech/corpus-v1.jsonl`: 40 Tamil, 40 English, 40 mixed, 96 development and 24 held-out prompts.
- A dependency-free Windows MCI recorder is available through `jarvis corpus-record`; it validates 16 kHz mono 16-bit PCM WAV and safely resumes by skipping existing files.
- The first five English recordings passed format validation. In the cold-process pilot, Base matched 2/5 and Small matched 4/5 exactly; both missed the controlled-noise prompt.
- Pilot RTF includes model startup for every short utterance. Persistent-engine timing must be added before final latency certification.
- All 40 English prompts are now recorded. Base achieved 27.5% exact match and 0.648 mean WER; Small achieved 38.5% exact match and 0.362 mean WER in the cold-process checkpoint.
- English audio has no clipping but is under-levelled: condition medians are about -32 to -34 dBFS, with several recordings below -40 dBFS. Preserve the raw WAVs and test bounded normalization before deciding on re-recording.
- One controlled-noise Small inference (`en_035`) hit the 120-second timeout; the bounded process supervisor recovered normally.
- Non-destructive normalization produced 40 derived English WAVs near -22 dBFS with zero clipping; raw audio was preserved.
- A loopback-only resident whisper.cpp HTTP adapter now pays model startup once and reports sustained timing.
- Resident normalized English results still fail certification: Base has 22.5% exact/0.504 WER/1.43 p95 RTF; Small has 42.5% exact/0.294 WER/5.16 p95 RTF.
- The calibrated `ta_001` take has -27.3 dBFS median speech-active RMS, -21.1 dBFS active p90, -13.1 dBFS peak and a -63.5 dBFS noise floor. Input level is accepted.
- The recorder now reports speech-active RMS separately from overall RMS and warns below -30 dBFS active level; target capture is roughly -28 to -20 dBFS active RMS.
- Ten Tamil prompts are recorded with healthy peaks and zero clipping after derived normalization.
- Tamil feasibility results reject generic Whisper: Base Q5_0 WER 0.885/p95 RTF 2.51, Small Q5_0 WER 0.873/p95 RTF 16.79, and Small F16 WER 0.870/p95 RTF 24.03; every profile had 0% exact match.
- The F16 control proves quantization is not the accuracy root cause. Candidate selection moves to a Tamil-specialized model under the acquisition gates in `deliverables/research/stt-challenger-gate.md`.
- A non-mutating network probe is ready at `scripts/probe-stt-challengers.ps1`; it records immutable model metadata, licenses, file sizes and Windows/Python 3.12 wheel-only resolver results without downloading weights.
- Natural spoken Tanglish is now the primary interaction target. English and Tamil remain acoustic controls.
- `storage/datasets/speech/dialogue-scenarios-v1.jsonl` contains ten original scenarios and 80 turns; `tanglish-owner-v2.jsonl` contains 40 owner prompts with eight held out by complete scenario.
- The v2 recorder uses situational elicitation and saves the words actually spoken. Copyrighted Tamil-dubbed movie dialogue is behavioral inspiration only and is not included in the corpus.
- The reviewed public Tanglish sources are variation/research inputs, not direct command truth; provenance and license gates apply before any training derivative.
- The five-file session consolidator binds actual speech and SHA-256 to the current WAV; future rerecords archive the superseded take before atomic replacement.
- Reference-text semantic evaluation passes 5/5. Generic Whisper Base auto, Small auto and Small forced-Tamil each preserve 0/5 semantic intents; STT is the active bottleneck.
- Pilot evidence is documented in `deliverables/reports/tanglish-v2-pilot.md`.
- Current quality gate: 99 tests passing, 85.05% coverage, Ruff clean, strict mypy clean and offline verification passing.

## Certified target hardware

- AMD Ryzen 5 7520U, 4 cores / 8 logical processors, 2.80 GHz base.
- 16 GB RAM (15.3 GB usable), LPDDR5-5500; approximately 8.1 GB available in the supplied snapshot.
- Integrated AMD Radeon graphics; do not require GPU inference acceleration.
- Windows 11 Home Single Language 25H2, OS build 26200.9457; virtualization enabled.
- 477 GB storage with approximately 216 GB free.

## Latest speech decisions

- Speech must be completely local, offline after model download, provider-free and CPU-only.
- Jarvis must understand natural Tamil-English code-switching, short contextual references, corrections and cancellation.
- Generic Whisper Small/Base are measured baselines but fail the current Tamil certification gate.
- Next conditional STT candidate: pinned Tamil-fine-tuned Whisper through a CPU-compatible runtime.
- AI4Bharat IndicConformer remains a future challenger; its native Windows/Python 3.12 NeMo dependency path and repository access fail the present Phase 1 gate.
- Primary TTS evaluation: Tamil MMS VITS versus AI4Bharat Indic-TTS.
- Initial mixed-language TTS strategy: one consistent Tamil voice with an editable English-to-Tamil pronunciation/transliteration dictionary.
- Emergency TTS fallback: eSpeak NG Tamil.
- Push-to-talk comes first; local wake word is added after the speech baseline is reliable.
- VAD direction: lightweight local WebRTC/Silero-style processing.

## Colibri inference lessons adopted

- Native compiled hot paths and quantized weights.
- Hard memory profiles and preflight admission.
- Bounded working buffers and no uncontrolled pagefile thrashing.
- Serialized heavyweight inference on constrained machines.
- One local inference scheduler prioritizing audio/VAD, STT, TTS, LLM and background work in that order.
- Hardware-specific certification instead of assuming every model is suitable for every CPU.

## Resume point

No additional owner recording is needed now. Keep `tg_006` onward and held-out scenarios unrecorded until the Tamil-specialized five-file gate is reviewed.

Next technical activity:

- Install the .NET 8 SDK before implementing the S1 ACL-protected named-pipe identity prototype.
- Convert and benchmark the pinned Tamil-fine-tuned Whisper source on the existing five files.
- Compare its semantic preservation, latency and memory with the rejected generic baselines.
- Implement the contextual downloads vertical slice: list, select, correct, copy request and cancel/confirm.
- Establish memory, real-time-factor, latency and accuracy gates for STT/TTS candidates.
- Select the certified speech profile for the target laptop.
- Verify and lock Python 3.12.10 dependencies for the benchmark harness and runtime services.
