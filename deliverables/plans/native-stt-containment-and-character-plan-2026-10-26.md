# Next phase plan: native STT containment and Jarvis character shell

Date: 2026-10-26  
Status: in progress; governed adapter certification passed, tiny ONNX fixture next  
Primary objective: certify the native speech-worker boundary before loading a real model, while
starting a low-resource Jarvis character shell that has no action or approval authority.

## Executive decision

The next critical-path increment is worker failure/cleanup certification followed by
`GovernedWorkerSlot` and Windows Job Object integration. The character is not postponed until the
entire voice stack is complete: its non-observing presentation shell can be developed in parallel
against synthetic state events. Microphone, screen observation, TTS lip-sync, action reporting and
approval integration remain gated behind their respective trusted services.

This preserves the architectural separation:

```text
STT worker -> untrusted transcript evidence -> companion/planner -> typed plan
                                                               |
Trusted runtime state -----------------------------------------+--> character presentation
                                                               |
Policy + separate trusted approval UI -> broker -> verifier ---+--> verified result presentation
```

The character may communicate state and request interaction. It cannot approve an action, forge an
execution result, operate the broker, or convert uncertain speech into authority.

## Current verified baseline

- Python control core: 311 tests passing; Ruff and strict mypy clean across 57 source files.
- Companion/planner held-out evaluation: 40/40, including Tanglish context, correction,
  clarification, cancellation and prompt-injection cases.
- Windows broker: 29 contract checks passing; real desktop execution remains disabled.
- Native speech memory ledger: 47 checks.
- Native engine ABI and deterministic fake backend: 63 checks.
- Bounded binary speech protocol/parser: 174 checks.
- Native child-worker process: 3,605 checks across 100 complete lifecycles, covering authenticated
  startup, streaming lifecycle, framing/bounds/auth/state rejection, injected failures, transport
  loss, cancellation/reset, PID cleanup, handle cleanup and fake-worker memory bounds.
- The worker still returns deterministic fake text. No real ASR model is in the runtime path.

### Progress recorded on 2026-10-26

Implementation-order steps 1 and 2 are complete. Exact compile-time test hooks now cover exit before
bootstrap, exit after bootstrap, backend-load rejection, exit/stall on audio and invalid UTF-8
output. Unknown controls are rejected, and the hook-enabled executable remains explicitly named
`jarvis_speech_fake_worker` rather than being a production worker.

The standalone portion of step 3 is complete: 100 authorized start/audio/final/shutdown lifecycles
leave no worker PID, keep the Python test process's handle count bounded, keep the fake worker below
64 MiB private memory, and show less than 16 MiB first-to-last median drift. Step 4 is also complete: the
disabled-by-default `native-stt-candidate` profile has a 512-MiB certification target and 640-MiB
process/job hard ceilings, and config tests prove those exact values.

### Progress recorded on 2026-10-28

The first step-5 adapter increment is complete. `NativeSpeechWorkerAdapter` now owns the provisional
lease, bounded binary pipes, one response reader, a bounded queue, monotonic operation deadlines,
strict session/sequence/UTF-8 validation and the speech lifecycle state machine. It assigns the
bootstrap PID through `GovernedWorkerSlot`, verifies membership using Windows `IsProcessInJob`, and
computes `START_AUTH` only after that verification succeeds.

Focused tests prove full fake streaming/cancel/reset/close behavior, normal-runtime denial of the
uncertified profile, fail-closed containment rejection, and cleanup after post-bootstrap exit,
invalid UTF-8 output and audio stall. A real Windows Job Object test reaches `READY` only after
verified containment and leaves no PID or memory lease. This focused increment was followed by the
complete governed certification below.

### Certification recorded on 2026-10-28

The complete governed fake-worker gate now passes. Eight injected exit/load/stall/invalid-output
cases plus cancellation cleanup were followed by 100 real Windows Job Object lifecycles. The run
passed 747 governed checks with zero surviving PIDs or leases, bounded handles, 47.0-ms startup p95,
16.0-ms maximum-response-latency p95, 843,776-byte peak private memory and 942,080-byte peak Job
memory. Evidence is stored in
`deliverables/reports/governed-native-speech-certification-2026-10-28.md`.

These small memory figures certify only the fake boundary. They do not predict model/runtime
residency. Implementation-order step 6 is now complete for the fake backend; step 9, the tiny pinned
ONNX inference fixture, is the critical-path next task. Character-shell scaffolding may proceed in
parallel but must not consume the heavy-worker slot or delay the ONNX containment proof.

The concrete ONNX execution and acceptance plan is
[`tiny-onnx-native-inference-gate-2026-10-28.md`](tiny-onnx-native-inference-gate-2026-10-28.md).

## Character decision already made

### Visual direction

The existing portrait and turnaround under `assets/character-references/` remain the visual design
reference: a stylized, approachable male companion with curly dark hair, beard, sunglasses, casual
red/navy plaid clothing and a relaxed walking posture. They are reference assets, not yet a rigged
production character; provenance and production-use rights must be recorded before shipping them.

The character lives in a transparent always-on-top window, normally in a reserved strip above the
Windows taskbar. It does not modify the taskbar or Windows shell. It can later walk, run, idle, turn,
look toward relevant UI, speak, display subtitles and move around menus/notifications. It supports
multi-monitor placement and click-through outside its interactive region.

### Personality

Jarvis is one consistent companion, not a visible committee of agents. The frozen interaction
qualities are:

- calm competence and friendly precision;
- warm, attentive and approachable without exaggerated enthusiasm;
- concise acknowledgements and occasional light situational wit;
- natural Tamil, English and Romanized/script-matched Tanglish;
- no claim of being human and no claim that an action succeeded without verifier evidence;
- one short clarification when required rather than guessing a target.

The current companion rubric already implements the text behavior: it mirrors the user's script,
keeps normal companion replies to roughly two short sentences, avoids filler, and separates
friendly speech from typed action proposals.

### Voice

The voice remains `jarvis-original-tanglish-v1`: an original warm low-to-mid register, calm and
confident energy, measured conversational pacing, clear consonants and natural code-switching in a
single identity. MMS Tamil is only a Tamil baseline/fallback because owner review found it too
robotic and monolingual. Vijay, an actor, a public figure or the fictional Iron Man JARVIS voice
will not be cloned. Any custom voice must use consent-cleared recordings and compatible rights.

### Trust and privacy

- The character is a presentation surface, not a security boundary.
- Trusted approval is displayed by a technically separate native dialog.
- Listening, screen observation, camera observation and private mode must always have visible,
  trustworthy indicators sourced from the runtime—not from model prose.
- Private zones can hide/pause the character and disable observation independently.
- No continuous observation or personal memory enters the character prototype.

## Workstream A: finish the speech-worker failure matrix

### A1. Make fault injection deterministic

Add test-only startup options or an internal test control that cannot be enabled in production:

- exit before bootstrap;
- exit after bootstrap but before authorization;
- reject or stall backend load;
- crash while listening;
- stall a chunk or finalization;
- emit an oversized, malformed or invalid-UTF-8 result;
- exit without releasing normally.

Production startup must reject test controls unless the executable is the explicit test build.

### A2. Complete protocol/process contracts

| Area | Required cases | Required result |
|---|---|---|
| Framing | fragmented/coalesced process input, bad magic/version/header size/type/flags | fail closed; bounded read; no backend call |
| Bounds | zero, exact maximum, maximum+1, odd PCM byte count | accept only legal sizes; no allocation growth |
| Identity | wrong session, sequence zero, replay, skip, overflow | one safe error at most; worker terminates or resets by policy |
| Authorization | wrong/truncated digest, duplicate `START_AUTH`, early session/audio | backend open count remains zero |
| State | audio before start, double start, finish/cancel/reset in every state | deterministic rejection; no ambiguous transition |
| Lifecycle | cancellation during bootstrap/load/listen/finalize | bounded termination and cleanup |
| Transport | parent closes stdin, child closes stdout, broken pipe | bounded exit; no busy loop |
| Failure | injected crash, startup/chunk/final timeout | supervisor reports typed reason; no orphan |
| Output | invalid UTF-8, output exhaustion, oversized transcript | transcript rejected; no evidence forwarded |

### A3. Soak and resource checks

Run at least 100 create/authorize/session/cancel-or-finish/destroy cycles. Record per cycle:

- process ID and final exit reason;
- current and peak private commit and working set;
- handle count;
- lease acquisition/release;
- startup, authorization, first partial and finalization latency;
- bytes and frames accepted.

Gate:

- zero surviving worker PIDs;
- zero active leases after every terminal path;
- zero unreleased Job handles/pipes;
- no monotonic private-commit growth greater than 16 MiB after warm-up;
- every timeout terminates within its configured grace period;
- malformed input never opens the backend.

## Workstream B: governed Python supervisor and Job Object

Reuse `src/jarvis/runtime/worker.py::GovernedWorkerSlot`; do not create a competing process manager.

### B1. Provisional policy

Add a disabled-by-default `native-stt-candidate` profile:

- certification target: peak private commit <= 512 MiB;
- experimental hard ceiling: 640 MiB;
- protected system floor: 4 GiB;
- maximum concurrent heavy workers: one;
- normal runtime use remains denied until certification.

### B2. Safe startup sequence

1. Acquire the provisional central memory lease.
2. Create bounded anonymous protocol pipes.
3. Spawn the native worker with no backend/model loaded.
4. Read and validate `BOOTSTRAP`: protocol, PID, capabilities, session and nonce.
5. Assign the exact PID to a capped Windows Job Object.
6. Query the Job Object to verify containment and configured limits.
7. Compute and send the session/nonce-bound `START_AUTH` digest.
8. Require `READY` inside the startup timeout.
9. Only now permit session/audio messages.

If any step fails, close pipes, terminate the Job Object, wait for process death, release the lease
and emit a typed failure. Never answer the authorization challenge before verified containment.

### B3. Runtime behavior

- Exactly one request reader owns worker stdout.
- Use bounded queues and explicit backpressure for PCM chunks.
- Enforce startup, per-chunk, finalization, cancellation and idle timeouts separately.
- Bind every response to session and sequence before exposing transcript evidence.
- Cancel cooperatively first, then close/terminate the job after a bounded grace period.
- Never close unrelated user applications to recover memory.

### B4. Supervisor exit gate

- All Workstream-A cases pass through the real supervisor.
- The fake backend cannot load before verified Job assignment.
- Injected crash/timeout/broken-pipe paths leave zero PIDs and leases.
- Job peak memory and worker-reported memory are stored with the run evidence.
- Normal Jarvis runtime remains simulation-only and cannot select the provisional worker.

## Workstream C: resource-bounded character shell

This work may run after A1/A2 stabilize; it must not interfere with Workstream-B certification.

### C1. Rendering choice

Use a Godot 4 transparent-window prototype, but begin with a lightweight 2D rig/sprite representation
derived from a rights-cleared character turnaround. This validates Windows overlay behavior and RAM
cost before deciding whether a full 3D VRM model is justified. A later 3D upgrade must pass the same
resource and interaction contract.

### C2. Trusted semantic animation contract

The LLM never controls bones, coordinates or animation clips. The overlay accepts an allowlisted
state packet from the trusted presentation adapter, for example:

```json
{
  "presence": "idle",
  "attention": "user",
  "expression": "warm-neutral",
  "intensity": 0.3,
  "gesture": "acknowledge",
  "speech_state": "silent",
  "privacy_state": "normal"
}
```

Fields are enums, intensity is clamped to `[0,1]`, unknown values become neutral, and event rate is
bounded. The local animation state machine performs transition blending, idle scheduling, gaze,
navigation and collision avoidance.

Initial states:

- hidden/private;
- idle;
- attention/wake;
- listening;
- thinking;
- speaking;
- waiting-for-user;
- waiting-for-approval;
- executing-unverified;
- completed-verified;
- blocked/error.

The visual distinction between `executing-unverified` and `completed-verified` is mandatory.

### C3. Prototype scope

1. Transparent click-through overlay above the taskbar.
2. Drag/reposition, monitor selection and persisted non-sensitive placement.
3. Idle/walk/listen/think/speak/error animations driven only by a synthetic state simulator.
4. Subtitle bubble with bounded text and safe font fallback for Tamil and English.
5. Visible microphone/screen/camera/private-mode indicators.
6. Pause, hide, stop-speaking and privacy controls.
7. No screen capture, microphone access, broker access, memory access or autonomous movement outside
   configured zones.

### C4. Character resource gate

Treat these as provisional targets to validate on the owner laptop:

- idle private commit <= 256 MiB;
- no monotonic growth greater than 16 MiB during a two-hour animation soak;
- idle CPU median <= 1% after settling;
- state-event queue is bounded and collapses obsolete transient events;
- overlay never steals focus during normal click-through operation;
- hiding/private mode stops animations and releases optional assets where practical.

If the 2D prototype misses these targets, optimize or use a smaller native renderer before attempting
3D. The character never competes with the single heavy model-worker slot.

### C5. Later character integration

After STT and TTS gates pass:

- drive listening/thinking/speaking states from trusted pipeline events;
- generate lip-sync from consent-cleared TTS phoneme/timing output or bounded amplitude fallback;
- map companion dialogue acts to restrained allowlisted gestures;
- show action progress only from the task ledger;
- show success only from broker/verifier evidence;
- open the separate trusted approval dialog for R2/R3 actions.

## Workstream D: protect the Jarvis personality

Create a small character-behavior regression pack independent of ASR and TTS. It should check:

- Romanized Tanglish input receives Romanized Tanglish, not forced formal Tamil;
- Tamil-script input may receive Tamil-script output;
- ordinary replies remain concise, warm and precise;
- light wit appears only when contextually appropriate;
- distress or serious requests suppress wit;
- clarification never invents an application/person/file;
- the character never says an action succeeded before verification;
- privacy mode and blocked states are explained plainly;
- animation expression matches the trusted dialogue/runtime state.

The existing 40/40 companion/planner pack remains the reasoning baseline. The new pack measures
presentation consistency, not authority.

## Implementation order

1. Add fake-worker deterministic fault hooks restricted to test builds.
2. Expand the child-process contract for malformed/auth/state/transport failures.
3. Add 100-cycle PID/handle/memory drift checks.
4. Add the provisional `native-stt-candidate` policy profile.
5. Implement the Python native-worker adapter around `GovernedWorkerSlot`.
6. Verify pre-authorization Job containment and finish supervisor fault tests.
7. In parallel after step 2, scaffold the non-observing Godot character shell and synthetic state
   simulator.
8. Add character state/resource/interaction contracts.
9. Prove a tiny pinned ONNX inference fixture inside the governed worker.
10. Run provenance-first Tamil/Tanglish ASR candidate triage and Gate B.
11. Resume expressive original Tanglish TTS selection.
12. Integrate STT, companion response, TTS and character only after their independent gates pass.

## Definition of done for this next phase

The phase is complete when:

- the fake speech worker passes the full failure matrix and 100-cycle soak;
- no tested failure leaves a worker PID, lease, pipe or material memory drift;
- backend load is demonstrably impossible before verified Job containment;
- a typed supervisor result distinguishes denial, timeout, crash, cancellation and clean completion;
- the character shell can render all trusted states from synthetic events within its provisional
  resource limits;
- the character cannot observe, approve, execute or report unverified success;
- the personality and original-voice decisions remain unchanged and regression-tested.

## Explicitly not included yet

- enabling a real ASR model in normal Jarvis runtime;
- microphone-always-on behavior or wake word;
- continuous screen/camera observation;
- real desktop action execution;
- permanent personal memory;
- final 3D/VRM production art;
- public-figure, actor or fictional-character voice cloning.

