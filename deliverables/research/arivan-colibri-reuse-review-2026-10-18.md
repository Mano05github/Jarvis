# Arivan and Colibri reuse review for Jarvis

Date: 18 October 2026

## Scope

Read-only review of:

- local Arivan checkout: `D:\arivan`;
- recorded Colibri upstream: `https://github.com/JustVugg/colibri`;
- Arivan origin: `https://github.com/Mano05github/Arivan`.

Network access to GitHub was unavailable during this review. Colibri evidence therefore comes from the pinned source import and provenance retained in Arivan, not a fresh comparison against GitHub.

## Provenance and current state

- Arivan is an Apache-2.0 source fork of Colibri v1.12.0.
- Recorded imported Colibri commit: `dcd73832f293750086643e1f0ccd2cd6d067259c`.
- Local Arivan commit: `fe687f7f2292415bccf3a7093fb62164368fe439` (`Harden cross-platform runtime tests`).
- The `D:\arivan\colibri` directory is empty because Colibri's source is incorporated into the repository root.
- Arivan version is `0.1.0.dev0`.
- Arivan explicitly says its 8 GiB profile is an admission-control contract, not yet proof that a full GLM-5.3 checkpoint works within the budget.

The local Arivan worktree contains owner changes and was not modified:

- modified: `c/Makefile`;
- modified: `c/tools/check_glm53_checkpoint.py`;
- modified: `docs/glm53-flash.md`;
- untracked: `c/tests/test_certify_glm53.py`;
- untracked: `c/tools/certify_glm53.py`.

## Focused validation performed

The review did not build engines or run model checkpoints. It ran dependency-light tests with bytecode writes disabled:

- CLI/profile/output group: 40 tests passed.
- OpenAI server, cancellation and supervisor group: 184 tests ran; 181 passed and 3 environment-specific tests were skipped.
- Machine-readable `16gb` profile output passed and declares a 12 GiB engine budget, 4 GiB OS reserve, 8,192-token context and one KV slot; the profile remains experimental.

The server tests exercised:

- OpenAI chat/completion framing;
- authentication and Host allowlisting;
- DNS-rebinding-style Host rejection;
- CORS handling;
- request size and malformed-body handling;
- connection/per-address limits and slow-client reclamation;
- bounded FIFO admission and HTTP 429 behavior;
- request cancellation and client disconnects;
- UTF-8 frame boundaries;
- stop-sequence filtering;
- context-limit errors;
- static-path traversal rejection;
- local image-path allowlisting;
- tool-call parsing boundaries;
- Windows Job Object child termination.

These tests are meaningful protocol evidence, but they do not certify model accuracy, full-checkpoint memory, or target-laptop latency.

## What Arivan/Colibri provides

### CPU-first model runtime

- Native C model-family adapters.
- Explicit 8/16/32 GiB memory profiles.
- Allocation accounting by load/prefill/decode/vision phase.
- Dense-layer, embedding, output-head and expert paging.
- Checked-integer admission before recurrent/KV state mutation.
- Binary search for the largest fitting prefill chunk.
- CPU/GPU/storage placement and telemetry.
- Token-exact tiny oracle and cross-platform tests.

### Local serving

- `POST /v1/chat/completions` and `/v1/completions`.
- Anthropic-compatible `/v1/messages`.
- Localhost default binding.
- Optional bearer/API-key authentication.
- Host allowlist.
- Bounded request body, connections, queue and timeout.
- Streaming, cancellation and explicit unsupported-feature errors.
- One to sixteen KV slots with common-prefix reuse.

### Structured/closed-set features

- `response_format` accepts JSON/JSON Schema/GBNF on engines with grammar-payload support.
- Important limitation: grammar is a speculative draft source, not a hard output constraint. Jarvis must still parse and validate every response.
- Brio mode scores a closed set of options and returns probabilities plus normalized entropy instead of generating an arbitrary string.

### Process lifecycle

- Windows Job Object support terminates an engine child when the supervisor handle closes.
- Cancellation and shutdown are tested across HTTP and engine protocol layers.

## Reuse decision matrix

| Component/idea | Decision | Jarvis use |
| --- | --- | --- |
| Hard memory admission | Adopt the algorithmic pattern now | Preflight combined STT/TTS/local-LLM memory and preserve OS headroom before starting a worker. |
| Phase/resource telemetry | Adopt selectively | Track worker startup, resident RSS, p95 latency, queue wait and available-system-memory floor. |
| Bounded FIFO scheduler | Adopt | Serialize heavy CPU inference on the four-core laptop; reject or defer overload instead of thrashing. |
| Windows Job Object lifecycle | Adopt for native/long-lived workers | Ensure broker, STT, TTS and optional local-LLM descendants die with their supervisor. |
| OpenAI-compatible server | Optional integration later | Connect through Jarvis's existing provider gateway over loopback; do not link engine code into the controller. |
| Brio closed-set scoring | Research prototype later | Possible uncertainty signal for unfamiliar intent/application selection; never policy or authorization. |
| JSON/GBNF draft generation | Use only as an optimization | Continue strict Jarvis JSON parsing, Pydantic validation and deterministic compilation. |
| KV prefix reuse | Useful with privacy controls | Reduce repeated system-prompt cost only when persistence is disabled or explicitly approved. |
| Tiny token-exact oracle pattern | Adopt for model/runtime candidates | Require synthetic fixtures plus real-checkpoint certification and exact/quality gates. |
| Model conversion/adapters | Do not import now | Large model families are unrelated to current speech and broker blockers. |
| Segment/Edge distributed ABI | Defer | Adds discovery, transport, lease and activation-boundary risk without helping Phase 1. |
| Tauri/Web dashboard | Do not merge into Jarvis | It is a model-runtime dashboard, not the Jarvis character/approval UI. Borrow telemetry concepts only. |
| Model-generated native tool calls | Reject as authority | Jarvis must keep `authority=none`, validate envelopes, compile actions and apply policy independently. |
| Tool-call salvage | Keep disabled | Recovery of malformed model tool syntax is inappropriate for consequential Jarvis actions. |

## Best immediate reuse: resource admission

Jarvis currently supervises individual benchmark processes, but it does not yet have a single admission controller for simultaneous speech, LLM and playback workloads.

Add a `ResourceAdmissionController` with a deterministic budget:

```text
available_system_memory
- protected_OS_headroom
- already_admitted_workers
- request_peak_estimate
>= safety_margin
```

Recommended initial rules for the 16.4 GB machine:

- reserve at least 4 GiB for Windows and interactive applications;
- use measured peak RSS plus a conservative startup/transient allowance;
- allow only one heavy inference worker to execute CPU-intensive inference at a time;
- permit resident workers only when the system-memory floor remains satisfied;
- reject before model load if even the smallest safe profile cannot fit;
- cancel queued work on user cancellation or deadline;
- record the admission decision without prompt/audio content.

For variable input sizes, adapt Arivan's monotonic fitting algorithm:

1. calculate the full requested chunk's conservative peak;
2. run unchanged if it fits;
3. otherwise binary-search the largest fitting chunk;
4. reject before mutating session state if one unit cannot fit;
5. never treat pagefile availability as safe RAM.

This pattern is useful for STT audio chunks, LLM prefill/context admission and future streaming TTS buffers.

## Best immediate reuse: worker liveness

Jarvis's current Python process supervisor recursively terminates children with `psutil`. Arivan additionally tests the Windows Job Object rule `KILL_ON_JOB_CLOSE`.

Recommended design:

1. create a Job Object per long-lived untrusted/native worker;
2. set kill-on-close and appropriate active-process/resource limits;
3. assign the process before accepting it as ready;
4. retain the Job handle in the supervisor;
5. close it during cancellation, crash recovery or controller exit;
6. keep the existing `psutil` tree termination as a diagnostic/fallback, not the primary Windows containment guarantee.

Apply first to the future Windows broker test host and optional local model server, then to STT/TTS workers after compatibility testing.

## Optional Arivan provider integration

Jarvis already supports `ProviderKind.OPENAI_COMPATIBLE`. The boundary should be HTTP over loopback:

```toml
[profiles.arivan-local]
provider = "openai_compatible"
endpoint = "http://127.0.0.1:8000/v1"
model = "OWNER-CERTIFIED-ARIVAN-MODEL-ID"
credential_ref = "jarvis/llm/arivan-local"
remote = false
timeout_seconds = 30
```

This is an example only; do not add it to the active local configuration until a real model passes the gates below.

Server launch requirements:

- bind exactly to `127.0.0.1`, not `0.0.0.0`;
- configure a random local API key through DPAPI/Jarvis secret storage;
- restrict allowed Host values to loopback/localhost;
- do not enable wildcard CORS;
- `COLI_DEBUG=0` so prompts are not printed;
- `KVSAVE=0` so prompt-derived KV state is not persisted;
- `USAGE_SAVE=0` during certification for reproducibility and fewer model-directory writes;
- one KV slot initially;
- bounded queue of one or two and a short queue timeout;
- supervise the server with a Windows Job Object;
- store model/cache/runtime outputs under approved storage, not the Jarvis source tree;
- disable/ignore native tool calls and `COLI_TOOL_SALVAGE`;
- Jarvis remains the only policy/action compiler.

### Compatibility concern

Jarvis always sends `response_format={"type":"json_object"}`. Arivan/Colibri supports that field only for engine families whose protocol advertises grammar payloads. Even there, grammar drafting is not hard enforcement. A model/server pair can therefore:

- reject Jarvis with HTTP 400 if its engine lacks grammar-payload support; or
- return non-JSON despite accepting `response_format`.

The exact engine/model pair must pass an integration smoke test before it is registered.

## Local-provider acceptance gate

Do not route normal Jarvis conversation to Arivan until all conditions pass:

### Integrity

- immutable Arivan source commit;
- reviewed build toolchain and binary digest;
- immutable model revision, license, weight hashes and conversion manifest;
- no unreviewed remote code;
- no dependency on the dirty development checkout for production startup.

### Protocol

- authenticated `/health` and `/v1/models` succeed on loopback;
- Jarvis `response_format=json_object` succeeds for the chosen engine;
- cancellation propagates through gateway, server and engine;
- provider errors map to Jarvis's normalized error codes;
- no tool call or reasoning text bypasses InteractionEnvelope validation.

### Quality

- run the same 40-case companion/planner pack;
- 100% on cancellation, clarification, prompt injection and action-plan canonicalization;
- no authority/schema violations;
- compare failures against Azure, not merely against random output;
- perform at least a 100-turn stability/resource-drift run after the functional gate.

### Performance/resource

- measured startup, time to first token, complete response latency, tokens/second and queue wait;
- preserve at least 4 GiB system headroom under the intended concurrent Jarvis workload;
- no sustained pagefile thrashing;
- p95 short-reply latency must remain usable; if it is slower than the remote route, register it only as an explicit privacy/offline mode, not an automatic normal fallback;
- test concurrently with the selected STT/TTS resident footprints before production use.

Arivan's documentation warns that disk-streamed very large models may require roughly an hour to prefill a 15k-token agent prompt and decode around one token per second. Those models are unsuitable for normal Jarvis conversation on this laptop. A materially smaller certified model or a future successful low-memory profile is required.

## Brio suitability

Brio is technically interesting because it returns probabilities and entropy for a closed set. Potential Jarvis experiments:

- choose among a small set of intent hypotheses supplied by the trusted parser;
- score candidate application IDs after STT evidence extraction;
- signal uncertainty and trigger clarification;
- compare closed-set scores with the primary LLM and deterministic decoder.

Limits:

- it is model confidence, not correctness or calibrated safety probability;
- documented disk-streaming examples take tens to hundreds of seconds;
- option wording/token length affects scores (`mean` versus `sum` is a policy choice);
- it must not make policy, approval or authorization decisions;
- for Jarvis's existing known command set, the deterministic decoder is already exact and approximately microseconds, so Brio would be worse.

Decision: defer until a small local model is certified and only evaluate it as a selective-classification signal.

## Colibri-specific decision

Arivan contains the pinned Colibri import plus additional memory-budget and GLM-5.3 work. Creating a second direct dependency on upstream Colibri would duplicate runtime risk.

When GitHub becomes reachable:

1. compare the pinned Colibri v1.12.0 import with the current upstream release;
2. review security, protocol and Windows lifecycle fixes since the import;
3. upstream or selectively port fixes into Arivan first;
4. let Jarvis depend only on a certified Arivan service contract, not on both codebases;
5. preserve Apache-2.0 notices and separately verify every model license.

## Changes to the Jarvis roadmap

Add these items without changing the main order:

### Milestone 0

- add a worker-level resource-admission design and tests;
- adopt virtual clocks/fault injection before copying process concepts;
- add a future provider compatibility test for `response_format` and cancellation.

### Milestone 2

- use the Windows Job Object lifecycle pattern in the broker/worker supervisor;
- do not use Arivan as the Windows capability broker.

### After the typed broker vertical slice

- run an isolated Arivan local-provider feasibility spike only if a realistically sized licensed model is available;
- keep Azure primary unless the local candidate passes the same quality gate;
- allow an explicit privacy/offline route only after memory/latency certification.

### During speech integration

- use one global resource scheduler for STT, TTS and any local LLM;
- serialize heavy CPU inference to avoid contention on the four-core target;
- do not assume an individually passing model fits when all resident services are combined.

## Final recommendation

Arivan/Colibri is useful to Jarvis primarily as a source of **resource-control, serving, cancellation and oracle-testing patterns**. Its OpenAI-compatible boundary makes an optional local provider feasible later. It is not currently a proven replacement for Azure, a speech engine, a policy system or a desktop broker.

Adopt the mature patterns now; integrate the runtime only after one exact model/hardware/profile combination is independently certified.
