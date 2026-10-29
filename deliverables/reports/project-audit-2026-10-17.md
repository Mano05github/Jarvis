# Jarvis Project Audit and Next Plan

Date: 17 October 2026  
Workspace: `D:\Projects\Jarvis`  
Scope: implementation, automated quality, benchmark evidence, datasets, model integrity, prerequisites, security boundaries, and end-to-end readiness.

## Executive conclusion

Jarvis currently has a strong **text-companion and safety-oriented prototype foundation**, but it is not yet a working voice-controlled Windows assistant.

The strongest completed slice is:

`typed text -> remote multilingual LLM -> validated InteractionEnvelope -> deterministic action compilation -> simulated policy/execution -> text response`

The missing production slice is:

`microphone -> acceptable Tanglish STT -> trusted turn controller -> digest-bound approval -> narrow Windows broker -> result verification -> accepted Tanglish TTS -> playback/barge-in`

The current state should therefore be described as **architecture and text-runtime validation complete; speech selection, trusted execution, and end-to-end integration incomplete**. A 40/40 LLM evaluation is valuable, but it does not mean the full Jarvis product is 100% complete.

## Audit methodology

The audit used fresh checks where they were safe and locally reproducible, and inspected retained evidence for expensive or owner-credential-bound runs.

Freshly executed:

- Ruff lint across the workspace.
- Strict mypy across 52 source files.
- Full pytest normally and with branch coverage.
- Five isolated repetitions of the timing-sensitive MMS worker startup test.
- Offline workspace verification across 92 Python files.
- `uv lock --check` using a workspace-local cache.
- `pip check` dependency consistency.
- CLI and system diagnostics.
- Model manifest verification for the registered Whisper and MMS models.
- Corpus/dialogue manifest validation plus independent referenced-file existence checks.
- Fresh deterministic Tanglish certification: 14 cases x 100 repetitions.
- Source-tree scan for stubs/placeholders and unimplemented service surfaces.

Inspected but not rerun:

- The Azure 40-case companion evaluation. It requires the owner's DPAPI-bound credential and a remote paid/provider-dependent request. The retained final artifact was checked instead.
- STT candidate benchmarks. These are expensive and their retained artifacts/reports already establish rejection.
- MMS audio generation. Model integrity, benchmark artifacts, waveform hashes in reviews, and owner scores were checked; rejected speech was not regenerated.

## Where the project is now

| Area | Current status | Evidence-based interpretation |
| --- | --- | --- |
| Architecture and contracts | Strong | v1.7 trust flow, typed contracts, schema exports, privacy routing, and provider-neutral LLM boundary exist. |
| Text companion/planner | Passed current evaluation | Final retained run passed 40/40 across ten categories. This is a small controlled pack, not broad independent production certification. |
| Multi-turn dialogue state | Implemented | Clarification, cancellation, correction, pending-field handling, bounded history, and fail-closed behavior are unit-tested. |
| Deterministic Tanglish helper | Certified for its narrow codebook | Fresh run passed 14/14, 1,400 stable calls, safe abstention, and 53.7 microseconds p95. It cannot handle open-domain conversation. |
| Action compiler | Very narrow | Only `app.open` for Notepad, Calculator, and Visual Studio Code is registered. `app.close` is not implemented. |
| Policy and execution | Simulation only | It produces `would_execute`; it cannot touch Windows. R1+ digest-bound approval is not implemented. |
| STT | Benchmark infrastructure mature; candidate selection failed | Every tested Tamil/Tanglish Whisper route failed the semantic gate. STT remains the largest speech-input blocker. |
| TTS | Benchmark infrastructure mature; voice selection failed | MMS runs locally but was rejected as the main voice. No expressive Tanglish production voice is accepted. |
| Speech datasets | Metadata complete; recordings incomplete | The canonical manifests validate, but most Tamil/mixed audio is not recorded. |
| Audit trail | Implemented but operational evidence limited | Metadata-only SHA-256 chains are implemented and tested. The current `storage/audit` directory contains no session logs, and the chain is not signed or rollback-proof. |
| Native/service applications | Not implemented | `apps`, `native`, and `services` contain README placeholders only. |
| End-to-end assistant | Not ready | STT, real execution, result verification, TTS playback, phrase cache, and barge-in are not connected. |

## Fresh quality results

### Passing checks

- Ruff: passed.
- Strict mypy: passed for 52 source files.
- Normal pytest: **188/188 passed** in 12.97 seconds.
- Offline workspace verification: passed for 92 Python files.
- Dependency lock: valid; 24 packages resolved by `uv lock --check`.
- Installed dependency consistency: `pip check` reported no broken requirements.
- Python runtime: CPython 3.12.10 from the project virtual environment.

### Coverage gate failure

The branch-coverage run produced:

- 4,802 statements.
- 751 missing lines.
- 1,260 branches, of which 416 were missing.
- Statement coverage: 84.36%.
- Branch coverage: 66.98%.
- Combined configured coverage: **80.75%**.
- Required gate: **85%**.

Therefore, the current quality gate is **not passing**, even though the normal test suite passes.

Important low-coverage production modules include:

| Module | Coverage |
| --- | ---: |
| `src/jarvis/llm/base.py` | 51.0% |
| `src/jarvis/benchmarking/qwen_semantic.py` | 56.5% |
| `src/jarvis/llm/openai_compatible.py` | 64.9% |
| `src/jarvis/cli/main.py` | 66.2% |
| `src/jarvis/llm/factory.py` | 66.7% |
| `src/jarvis/llm/anthropic.py` | 69.0% |
| `src/jarvis/llm/gateway.py` | 70.7% |
| `src/jarvis/llm/azure_openai.py` | 72.7% |

The coverage evidence is retained at `storage/benchmarks/results/audit-20261017-coverage.json`.

### Timing-test instability

Under coverage instrumentation, one test failed:

`test_mms_worker_reports_startup_exit_without_waiting_for_timeout`

Observed elapsed time was 3.618 seconds against an absolute assertion of less than 3.0 seconds. The full suite without coverage passed, and the same test passed in five isolated repetitions. This indicates a brittle wall-clock assertion rather than a proven MMS worker defect. It still matters because it makes the instrumented quality gate unreliable.

Recommended correction: assert that an early worker exit is detected materially before the configured startup timeout, with a platform/instrumentation-tolerant bound. Preserve the behavioral guarantee without depending on a universal three-second wall clock.

## LLM companion and planning analysis

### What is working

The retained final Azure run at `storage/benchmarks/results/llm-companion-20261013T143522Z` passed 40/40:

- ambiguity: 4/4
- anaphora: 4/4
- cancellation: 4/4
- clarification: 4/4
- companionship: 4/4
- correction: 4/4
- knowledge: 4/4
- multi-step planning: 4/4
- planning: 4/4
- prompt injection: 4/4
- provider failures: 0
- median latency: 3.93 seconds
- maximum latency: 5.83 seconds

The provider configuration validates and routes companion/planner requests to an Azure deployment. Credentials are referenced through the user-bound DPAPI store rather than embedded in the TOML file.

### Remaining limitations

- The evaluation pack has only 40 cases and was used during iterative rubric remediation. It is strong regression evidence, not independent real-world certification.
- The final run depends on one remote Azure route. The configured fallback order is empty.
- Earlier runs experienced `model_unavailable` and HTTP 400 provider failures, proving provider availability is an operational dependency.
- A roughly four-second median model latency is acceptable for a prototype text interaction but will feel slow once STT, approvals, execution, and TTS are added.
- Prompt-injection evidence contains only four cases. Tool authority is correctly withheld, but broader adversarial testing is still required.
- The local Ollama profile is a placeholder (`your-local-model`) and is not a usable private-local fallback.

## Dialogue, policy, and action analysis

### What is working

- Bounded conversation history.
- Clarification questions and resumption.
- Correction and cancellation handling.
- Pending clarification expiration and stale-state consumption.
- Rejection of unknown actions, applications, and extra arguments before policy.
- Simulation records are allowlisted and do not give the LLM execution authority.

### Current behavioral boundary

Only these resources can compile:

- `application:notepad`
- `application:calculator`
- `application:visual-studio-code`

Only `windows.application.open` is registered. This explains why Jarvis can ask which of three sample apps to open but cannot close Calculator. The three-app list is an intentional narrow allowlist, not app discovery.

### Missing safety/execution work

- No digest-bound pending approval for R1+ actions.
- No approval expiry/replay protection at the action boundary.
- No signed or identity-checked Windows broker.
- No ACL-protected named-pipe transport.
- No OS-level result verification.
- No `app.close` contract/compiler/policy/broker capability.
- No user-configured application registry or safe discovery mechanism.
- No real executor; direct `Start-Process` from the model/controller must remain forbidden.

## Deterministic Tanglish helper

The fresh 17 October run at `storage/benchmarks/results/deterministic-tanglish-v1-20261017T143734Z` passed:

- 14/14 exact semantic packets.
- 1,400/1,400 stable decoder calls.
- 100% deterministic-gate validity.
- 100% oracle exact accuracy.
- 100% required safe abstention.
- 27.75 microseconds p50 and 53.7 microseconds p95.
- 438,272-byte observed RSS growth.

This component is valuable as a regression baseline, safety-marker detector, or fast path for a reviewed vocabulary. It must not become a vocabulary ceiling for natural Tanglish companionship.

## STT analysis

STT is currently the most serious speech-input blocker. The project has high-quality benchmarking infrastructure—resident workers, bounded process supervision, PCM validation, memory/CPU measurement, WER, semantic scoring, and retained reports—but none of the tested candidates is acceptable for natural owner Tanglish.

Measured outcomes include:

- Normalized English Whisper Base: 22.5% exact, 0.504 WER, 1.43 p95 RTF.
- Normalized English Whisper Small: 42.5% exact, 0.294 WER, 5.16 p95 RTF.
- Tamil Base: 0% exact, 0.885 WER, 2.51 p95 RTF.
- Tamil Small: 0% exact, 0.873 WER, 16.79 p95 RTF.
- Tamil Small F16 control: 0% exact, 0.870 WER, 24.03 p95 RTF.
- Generic Whisper variants on the five natural Tanglish files: 0/5 semantic intents preserved.
- Tamil-specialized Vasista model: 1/5 strict semantic success, 0/4 required slots, 1.067 WER, 1.80 p95 RTF.
- Whisper Large-v3-turbo: 0/5 semantics; 7.21 forced-Tamil and 19.88 auto-language p95 RTF, about 1.09 GiB RSS.
- Whisper Large-v3: 1/5 semantics, 0/4 required slots, 12.77 p95 RTF, about 2.15 GiB RSS.

The evidence shows that increasing Whisper size did not solve code-switch semantic preservation on this hardware. Integrating one of these rejected profiles as if it were production-ready would only move errors downstream into the planner.

Recommended STT rule: transcripts remain untrusted evidence. Low-confidence or semantically incomplete commands must clarify, never silently execute.

## TTS analysis

### MMS technical result

The verified MMS Tamil model completed 12/12 development prompts:

- startup: 0.386 seconds
- mean complete synthesis: 1.782 seconds
- p95 complete-waveform audio-ready: 3.561 seconds
- p95 RTF: 1.208
- peak RSS: 578,465,792 bytes (about 552 MiB)

This is a valid offline Tamil baseline, but it is non-streaming and does not provide time-to-first-audio evidence.

### Owner listening result

The phonetic Tanglish stopgap completed 4/4 technically:

- startup: 0.493 seconds
- mean synthesis: 3.592 seconds
- p95 audio-ready: 4.583 seconds
- p95 RTF: 1.007
- peak RSS: 581,095,424 bytes

Owner review accepted only 2/4:

- intelligibility mean: 3.5/5
- pronunciation mean: 3.5/5
- naturalness mean: 3.0/5
- Jarvis voice fit mean: 3.25/5
- conversation sample: rejected as robotic
- command sample: 1/5 on every scored dimension
- technical and number/date samples: accepted

Therefore MMS phonetic Tanglish is rejected as the primary Jarvis voice. It may remain a fallback/evidence baseline.

### Candidate status

- AI4Bharat Indic-TTS: rejected for monolingual/fixed delivery and legacy deployment evidence.
- IndicF5: source inspected, but model access, license, English/code-switch evidence, and CPU performance remain unresolved; rejected under the current gate.
- Indic Parler-TTS: promising description-conditioned design, but anonymous model access failed and licensing/code-switch/CPU feasibility remain unproven; no weights were downloaded.
- eSpeak NG: emergency intelligibility fallback only; executable is not installed in project storage.

No accepted friendly, expressive Tanglish voice currently exists. The earlier public-figure voice request is explicitly deferred; production work must use an original, consent-cleared voice rather than an identifiable actor/public figure imitation.

## Dataset analysis

### Structurally valid manifests

- Canonical speech manifest: 120 rows—40 English, 40 Tamil, 40 mixed; 96 development and 24 held-out.
- Normalized manifest: same declared distribution.
- Dialogue scenarios: 10 scenarios, 80 turns, 8 development and 2 held-out.
- Owner Tanglish manifest: 40 prompts, 32 development and 8 held-out.
- TTS evaluation pack: 24 original prompts, balanced across Tamil, English, and mixed; 12 development and 12 held-out.

### Actual audio completeness

Independent file-existence checks found:

| Dataset | Referenced | Existing | Missing |
| --- | ---: | ---: | ---: |
| Canonical raw corpus | 120 | 50 | 70 |
| Canonical normalized corpus | 120 | 50 | 70 |
| Owner Tanglish v2 | 40 | 5 | 35 |

Actual raw audio:

- English: 40/40.
- Tamil: 10/40.
- Canonical mixed: 0/40.
- Separate natural Tanglish v2 pilot: 5/40.

The manifests are prompt plans, not proof that recordings exist. CLI validation currently validates structure/distribution but does not fail because referenced audio is absent. Reporting must always show both manifest size and actual file completeness.

Held-out speech should remain sealed until a candidate passes development gates. Recording every missing held-out prompt now would weaken future certification.

## Model integrity and provenance analysis

Fresh `model-verify` results:

- Whisper Base multilingual Q5_0: passed.
- Whisper Small multilingual Q5_0: passed.
- Facebook MMS Tamil pinned model: passed.
- Qwen3-8B Tanglish Q4_K_M manifest: **failed schema validation**.

The Qwen file is stored under `storage/models/llm/manifests`, but it uses a conversion-specific schema (`repository_id`, `revision`, `source_weights`, `gguf_file`, and related fields) rather than the canonical `ModelManifest` accepted by `jarvis model-verify`. The CLI emits an unhandled Pydantic traceback.

This does not make the rejected Qwen runtime a production blocker, but it is a repository-integrity defect. Either:

1. define and route a versioned conversion-manifest schema and verifier, or
2. move/rename the file so users cannot reasonably expect `model-verify` to accept it.

Invalid manifest input should produce a concise structured error instead of a traceback.

## Audit, privacy, and security analysis

Positive controls:

- LLM output has no authority and must pass typed validation/compilation.
- Privacy routing blocks prohibited/local-only material from remote fallback.
- Credentials are not stored directly in provider configuration.
- Conversation audit accepts allowlisted metadata, not prompt/reply text or secrets.
- Each audit event binds the prior digest and is fsynced.
- Unknown actions and resources fail closed.

Remaining gaps:

- Hash chaining detects edits within a retained chain but is not signed; an attacker able to replace the whole file can recompute it.
- No external anchor, monotonic counter, or protected ledger prevents deletion/rollback.
- The current `storage/audit` tree contains no retained session logs, so there is no operational session evidence to inspect in this workspace at audit time.
- R1+ approvals are not digest-bound or implemented.
- The native broker identity/ACL boundary is not implemented.
- The prompt-injection pack is too small to represent a full adversarial review.
- Remote LLM routing adds privacy and availability dependencies even though release rules exist.

## Machine and prerequisite analysis

Target observed:

- Windows 11 x64.
- 4 physical / 8 logical CPU cores.
- 16.4 GB RAM total; about 6.1 GB available during audit.
- About 159.5 GB free on the project volume.
- Python 3.12.10.

.NET status:

- .NET 8 and .NET 10 runtimes are installed.
- **No .NET SDK is installed.**

The planned Windows broker cannot be built until a supported SDK—currently the plan specifies .NET 8 SDK—is installed. This is a development prerequisite, not an application runtime issue.

The initial `uv lock --check` failed because the managed audit process could not access the user's default uv cache. Repeating with a workspace-local cache passed immediately. This is an environment/cache-permission issue, not lock corruption.

## Documentation consistency findings

The checkpoint correctly marks its newest section as superseding older history, but old numbers and obsolete next steps remain in the same files. Examples include historical 69/99/110/185-test checkpoints and the older MMS-versus-Indic-TTS plan.

The newest checkpoint says 188 tests pass, which remains true without coverage, but it omits the newly measured 80.75% coverage failure. Future checkpoint updates should explicitly separate:

- test pass count,
- lint/type status,
- coverage result and threshold,
- live-provider evidence date,
- artifact-based evidence date,
- product-capability readiness.

## Prioritized issue register

### Product-critical blockers

1. **No acceptable Tanglish STT engine.** Rejected transcripts cannot safely drive actions.
2. **No accepted expressive Tanglish TTS voice.** MMS is technically functional but owner-rejected.
3. **No trusted real Windows executor/broker.** All actions are simulation-only.
4. **No end-to-end voice pipeline.** STT, turn controller, execution, verification, TTS, playback, and interruption are not connected.

### High-priority engineering gaps

5. Coverage is 80.75%, below the 85% gate.
6. R1+ approval state is not bound to an exact plan digest and expiry.
7. The .NET SDK prerequisite for the Windows broker is missing.
8. Speech recordings are incomplete: 70 canonical files and 35 owner-Tanglish files are absent.
9. Qwen's stored manifest is incompatible with the advertised verifier.
10. The remote LLM route has no configured fallback and has demonstrated transient failures.

### Medium-priority reliability/maintainability gaps

11. A startup timing test is instrumentation-sensitive.
12. Audit chains are unsigned and no live session audit files are currently retained.
13. CLI error handling leaks a traceback for incompatible manifests.
14. The action registry is limited to three opens and has no close operation.
15. Main LLM latency is already roughly four seconds before speech and execution overhead.
16. Progress/checkpoint documents mix current and historical truth, making status easy to misread.

## Recommended next plan

### Stage 0 — Restore a truthful green engineering baseline

Do this before adding another large feature.

1. Replace the brittle three-second MMS startup assertion with a behavior-based, timeout-relative test.
2. Add branch tests for the LLM gateway/transports, CLI failure paths, provider normalization, audit integrity failures, and action rejection paths.
3. Raise combined branch coverage from 80.75% to at least 85%.
4. Add a schema/verifier for conversion manifests or relocate the Qwen conversion record; return structured CLI errors.
5. Update the current checkpoint with the audit findings and remove stale “all gates pass” wording.

Exit gate: Ruff, strict mypy, normal pytest, coverage pytest, lock check, dependency check, and workspace verification all pass in one documented run.

### Stage 1 — Complete the trusted typed-action vertical slice

1. Implement pending R1+ approval with exact plan digest, expiry, single use, cancellation, and replay rejection.
2. Install the .NET 8 SDK.
3. Build a minimal ACL-protected named-pipe Windows broker with explicit caller identity and a tiny capability protocol.
4. Connect only `app.open` first; keep simulation as the default mode.
5. Add OS-level verification that the requested process/window actually opened.
6. Add `app.close` only as a separate typed capability with target resolution, ambiguity handling, risk classification, and verification.
7. Do not allow arbitrary executable paths or direct model-generated process commands.

Exit gate: typed Notepad/Calculator/VS Code open requests can be simulated and, only in explicit real mode, approved, brokered, verified, and audited. Unknown apps/actions remain denied.

### Stage 2 — Resolve speech input without weakening trust

1. Freeze the rejected Whisper profiles as baselines; do not spend more time scaling generic Whisper on this CPU.
2. Survey only clearly licensed, locally runnable Tamil-English code-switch candidates with evidence of Windows/CPU feasibility.
3. Use the existing five natural Tanglish development recordings as the first unbiased gate.
4. Require semantic-intent/slot preservation, not only WER.
5. Integrate STT into the turn controller only as untrusted evidence with confidence/clarification gates.
6. Start with push-to-talk. Add wake-word and barge-in only after accuracy and latency gates pass.

Exit gate: a development candidate preserves all safety-critical markers and required slots at usable latency on the target laptop. Only then record more development speech; keep held-out recordings sealed until final certification.

### Stage 3 — Select an original expressive Tanglish voice

Two legitimate paths remain:

1. Securely authorize read-only model-repository access for metadata/license inspection of a genuinely promising expressive candidate; never paste tokens into chat or store them in the repository.
2. Move to a consent-cleared original custom-voice path with explicit dataset/model licensing and a non-public-figure voice target.

Whichever path is chosen must pass:

- Tamil-English code switching without manual phonetic failures.
- Friendly, calm, confident, lightly witty delivery.
- Original identity; no recognizable actor/public figure imitation.
- Owner listening on development prompts.
- CPU memory, p95 latency/RTF, offline, provenance, and license gates.

Exit gate: all development categories meet the frozen listening threshold. Only then unseal held-out TTS prompts.

### Stage 4 — Integrate the end-to-end assistant

Connect:

`push-to-talk -> local STT evidence -> context/privacy release -> LLM -> typed validation -> policy/approval -> broker -> verification -> response text -> TTS -> playback`

Then add:

- cancellation during every stage,
- bounded timeouts and process cleanup,
- phrase/pronunciation cache,
- playback interruption/barge-in,
- privacy-safe metrics,
- crash recovery and audit continuity,
- offline/provider-unavailable behavior.

### Stage 5 — Broaden certification

1. Expand adversarial LLM tests beyond four injection cases.
2. Add noisy-room, fast-speech, corrections, anaphora, mixed script, numbers, names, and failure-recovery speech cases.
3. Complete remaining development recordings after a viable engine exists.
4. Preserve held-out prompts until the pipeline is frozen.
5. Run longevity, memory-drift, provider-failure, broker-restart, and replay/rollback tests.

## Immediate recommendation

The next coding work should be **Stage 0**, followed by **digest-bound approval state**. These are local, deterministic, and unblock trustworthy progress without waiting for a speech-model decision.

In parallel, the owner prerequisite is to install the .NET 8 SDK before broker work. TTS candidate hunting should not block the typed trusted-action vertical slice, and rejected STT/TTS engines should not be integrated as production defaults merely to make an end-to-end demo appear complete.

## Bottom line

Jarvis has a credible foundation, excellent retained benchmarking discipline, a strong current text/planning result, and a safe authority boundary. Its largest problem is not “the AI brain”; it is the gap between validated text simulation and a reliable real-world assistant. The project should now concentrate on truthful green quality gates, approval/broker security, and viable speech engines—then integrate one narrow end-to-end capability before expanding the app catalog.
