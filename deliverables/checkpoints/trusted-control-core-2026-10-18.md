# Trusted control-core checkpoint — 2026-10-18

## Outcome

Milestone 0 and the Python portion of Milestones 1–3 are complete. Jarvis is still
simulation-only; no change in this checkpoint can launch or close a real application.

## Implemented

- Replaced the timing-fragile MMS worker assertion with a timeout-relative early-exit check.
- Converted the Qwen GGUF record to the canonical `ModelManifest` schema and updated its
  acquisition and benchmark scripts to keep canonical integrity metadata separate from
  conversion provenance.
- Added an explicit trusted task lifecycle with legal transitions and terminal-state guards.
- Added deterministic canonical JSON and SHA-256 binding for compiled plans.
- Added an HMAC-authenticated, short-lived, session/task/payload-bound approval store.
- Approval consumption is atomic and single-use; expiry, replay, correction, cancellation,
  cross-session use, cross-task use, and payload mutation fail closed.
- Added a deterministic maximum-risk lattice over exact policy-decision coverage.
- Moved the application allowlist into `config/applications.toml`.
- Added typed `app.close` compilation. Graceful close is R2/ASK because unsaved work may be
  present. Force termination remains unregistered.
- Wired close proposal, confirmation, cancellation, correction, and expiry into the text
  conversation controller. Confirmed actions remain simulations.
- Added provider/network failure tests and bounded llama.cpp server-adapter tests to restore
  the configured branch-coverage gate without lowering it.

## Certification evidence

- `pytest --cov=jarvis --cov-branch`: **259 passed**, **85.24%** total branch coverage.
- Coverage JSON: `storage/benchmarks/results/phase2-control-core-coverage.json`.
- Ruff: pass.
- Strict mypy: pass across 53 source files.
- Qwen `model-verify`: canonical manifest parses; verification reports that the declared GGUF
  asset is absent at `storage/models/llm/gguf/...Q4_K_M.gguf`.

## Current boundary

- Real execution is not implemented.
- .NET SDK 8.0.426 is installed and the native broker has 29 passing contract checks.
- Faster-Whisper now has a governed certification path: the model load is startup-gated until
  its PID is assigned to a capped Job Object, and cancellation releases the process and lease.
  The pinned converted model was reacquired successfully. The first certification attempt was
  safely denied under soft pressure: about 4.26 GiB was available against a 2.81 GiB reservation
  and a protected 4 GiB floor. No STT worker was launched and no lease was retained.
- The workspace is not a Git checkout (`.git` is absent), so this checkpoint cannot include a
  commit hash or Git diff.

## Next implementation order

1. ~~Install the .NET 8 SDK and verify `dotnet --list-sdks`.~~ Completed: SDK 8.0.426.
2. ~~Create the non-executing C# named-pipe foundation with per-user access, bounded/versioned
   messages, caller SID verification, and no shell surface.~~ Completed.
3. ~~Add broker-owned DPAPI/HMAC capability authentication and bounded atomic replay
   protection.~~ Completed. Native broker certification now has 29 passing checks.
4. ~~Add resource admission, an identification-SQOS Python pipe client, and Windows Job Object
   containment before enabling any action.~~ Completed. The integration test starts the real
   broker, verifies health and caller binding, closes the job, and confirms no broker PID remains.
5. ~~Add a machine-wide memory governor before enabling model workers.~~ The first milestone is
   complete: strict config-backed profiles, atomic leases, physical and commit headroom checks,
   pressure classification, deterministic eviction ordering, and enforceable process/job memory
   caps. The broker is governed. STT, TTS, and local-LLM profiles remain uncertified and therefore
   cannot receive leases.
6. Memory-certify and integrate STT/TTS/local-LLM workers one at a time. Faster-Whisper containment
   integration is complete, but its profile awaits repeatable measurement. TTS and local LLM have
   not yet been integrated. Then add the broker-owned exact-path Notepad registry and verified
   launch implementation.

Native low-memory STT groundwork is now present in `native/Jarvis.SpeechRuntime`. Its clean-room C
ledger separates private commit from physical/file-backed residency, accounts resource categories
and phases, performs overflow-safe monotonic chunk fitting, and supplies a fixed caller-owned arena.
The versioned engine-neutral ABI now adds strict PCM16 mono 16 kHz validation, lifecycle enforcement,
cancellation/reset, bounded caller-owned results, adaptive chunk admission, and guaranteed temporary
workspace release around backend calls. A deterministic fake backend verifies that memory denial never
reaches inference and that errors cannot bypass cleanup. The warning-clean MSVC suite passes 47 memory
checks plus 63 engine checks. This is a host contract, not a real ASR backend, and deliberately does not
certify Large-v3-turbo: that model already failed Jarvis's Tanglish semantic gate and remains a regression
baseline only.

Latest Python certification: 303 tests passed with 85.16% branch coverage. Coverage evidence:
`storage/benchmarks/results/governed-stt-coverage.json`.
7. Implement allowlisted `app.open` with process plus top-level-window postcondition evidence.
8. Implement approval-gated graceful `app.close`; return `needs_user` when an unsaved-work
   dialog appears. Do not add force close in this vertical slice.
9. Authenticate broker receipts and append metadata-only audit events.
10. Run replay, expiry, cancellation, broker-crash, orphan-process, and repeated open/close
   certification tests before enabling an explicit real-execution mode.
