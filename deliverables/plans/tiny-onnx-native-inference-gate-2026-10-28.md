# Tiny native ONNX inference gate

Date: 2026-10-28  
Status: proposed immediate implementation plan  
Purpose: prove that a real native inference runtime can be loaded, executed and destroyed inside
Jarvis's governed worker boundary before evaluating any speech model.

## Decision

The next increment uses a tiny deterministic tensor model, not an ASR model. Passing this gate must
demonstrate the runtime lifecycle, containment, provenance, bounded memory, deterministic inference,
failure cleanup and repeatability. It must not claim Tamil/Tanglish accuracy.

The production Python environment will not import ONNX, ONNX Runtime, PyTorch, Transformers or
NeMo. The worker uses the ONNX Runtime C API behind the existing Jarvis speech-engine ABI. Any
one-time fixture generator remains isolated developer tooling; the committed fixture is hash-bound
and can be used without the generator.

## Non-negotiable invariants

1. The ONNX DLL and model are not loaded before verified Windows Job Object containment.
2. The controller never supplies a shell command, arbitrary DLL name or arbitrary model path.
3. Runtime, model and manifest are pinned by immutable version and SHA-256.
4. Normal Jarvis runtime cannot select the uncertified adapter.
5. A runtime/model failure produces no transcript evidence and no action proposal.
6. Job, PID, pipes, native allocations and central lease are released on every terminal path.
7. The existing 4-GiB protected system floor and 640-MiB hard Job limit remain unchanged.

## Target architecture

```text
Python certification controller
  -> provisional native-stt-candidate lease
  -> backend-unloaded native worker
  -> assign exact PID to 640-MiB Job Object
  -> verify IsProcessInJob and limits
  -> START_AUTH bound to session + nonce + approved manifest digest
  -> load pinned ONNX Runtime DLL through fixed adapter configuration
  -> validate pinned fixture hash
  -> create session with bounded threads/arena policy
  -> run deterministic tensor inference
  -> return bounded fixture result and metrics
  -> destroy session/runtime and close Job Object
```

The fixture adapter implements `JarvisSpeechBackendOps`; the controller and protocol do not depend
on ONNX-specific types.

## Work package 1: provenance-only acquisition plan

Before downloading binaries, create a machine-readable manifest containing:

- official publisher and canonical source URL;
- exact ONNX Runtime release version;
- Windows x64 CPU-only artifact name and expected size;
- release/package SHA-256;
- extracted `onnxruntime.dll`, import library and header SHA-256 values;
- MIT licence text SHA-256;
- fixture filename, opset, input/output schema, byte size and SHA-256;
- acquisition timestamp and tool version;
- allowed execution providers: CPU only.

Use an official Microsoft release/package source. Do not accept community DLL mirrors. Acquisition
must write under `storage/engines/onnxruntime/<version>/`; model bytes belong under
`storage/models/stt/fixtures/<fixture-id>/`. No binary is committed to source directories.

Add two scripts:

- `scripts/inspect-onnxruntime-source.ps1`: metadata, licence and hash-plan inspection without
  activation;
- `scripts/acquire-onnxruntime-fixture.ps1`: explicit acquisition, hash verification and immutable
  manifest generation.

The acquisition script must fail closed on redirects to an unexpected host, size mismatch, hash
mismatch, missing licence, architecture mismatch or an existing directory with different bytes.

## Work package 2: deterministic fixture

Use a small float32 graph whose output is independently calculable:

```text
input x: [1, 4]
y = ReLU((x * 2) + 1)
test x = [-2, -1, 0, 2]
expected y = [0, 0, 1, 5]
```

Requirements:

- one fixed input and one fixed output;
- static shape `[1,4]`;
- only basic operators such as `Mul`, `Add` and `Relu`;
- no custom operators, external data, dynamic dimensions or initializers outside the file;
- small enough to audit and hash directly;
- canonical source specification and generator revision recorded;
- expected output computed in the test rather than copied from runtime output.

Compare float results with absolute tolerance `1e-6`. Reject wrong type, shape, element count,
non-finite output or unexpected additional outputs.

## Work package 3: native ONNX adapter

Create a separate adapter rather than adding ONNX calls to protocol or memory code:

```text
native/Jarvis.SpeechRuntime/
  include/jarvis_speech_onnx_fixture.h
  src/jarvis_speech_onnx_fixture.c
  src/jarvis_speech_onnx_fixture_worker.c
  tests/speech_onnx_fixture_tests.c
```

The adapter lifecycle is:

```text
UNLOADED -> RUNTIME_LOADED -> SESSION_READY -> INFERENCING
         -> SESSION_READY -> DESTROYED
```

Any illegal transition becomes `FAULTED`. Destruction must be idempotent at the worker orchestration
layer even when partial initialization failed.

### Runtime configuration

Start with the most conservative CPU configuration:

- CPU execution provider only;
- sequential execution;
- one intra-op thread;
- one inter-op thread;
- thread spinning disabled where supported;
- graph optimization explicitly selected and recorded;
- CPU memory arena disabled for the first baseline, then compared with a capped arena only if
  measured latency justifies it;
- no global environment shared across worker processes;
- no dynamic DLL/provider discovery outside the pinned directory.

Use ONNX Runtime's allocator APIs, but treat Windows Job Object accounting as the authoritative hard
limit. Runtime allocator statistics never replace OS commit/working-set measurements.

### Manifest-bound authorization

Upgrade the real fixture worker's start challenge to:

```text
SHA256(
  "jarvis-stt-start-auth-onnx-v1" ||
  session_id ||
  nonce ||
  manifest_sha256
)
```

The worker may read and hash the small approved manifest before authorization, but it may not load
the runtime DLL or model until the digest matches after verified Job containment. The fake-worker v1
challenge remains unchanged for regression compatibility.

The worker validates that all resolved runtime/model paths remain within their configured immutable
storage roots and that the current bytes still match the manifest.

## Work package 4: inference and memory algorithms

### Allocation discipline

- precompute tensor byte counts with overflow-checked multiplication;
- enforce exact input/output rank, dimensions and float32 element size;
- allocate caller-owned input/output buffers from the existing fixed arena where practical;
- cap all runtime-returned names and metadata before copying;
- release `OrtValue`, type information, status, session, options and environment in reverse order;
- zero or discard output buffers after each run.

### Deadline model

Use monotonic absolute deadlines for:

- manifest verification;
- runtime/DLL load;
- session creation;
- inference;
- teardown.

The first fixture implementation may terminate the entire Job Object on an inference timeout. Do
not attempt unsafe thread cancellation inside ONNX Runtime. Later cooperative termination can use a
runtime-supported run-termination API only after a separate contract test.

### Resource measurements

Record per cycle:

- containment verification time;
- manifest verification time;
- DLL/runtime load time;
- session creation time;
- inference time;
- teardown time;
- private bytes and working set;
- Job peak process/job memory;
- handle and thread counts;
- exit reason and cleanup duration.

Use median, p95 and maximum. Compare the median of the first ten and last ten post-warm-up cycles for
drift rather than relying only on the final process sample.

## Work package 5: test ladder

### Level A: pure adapter contracts

- checked tensor-size arithmetic;
- valid and invalid shapes/types;
- exact output validation;
- partial initialization cleanup;
- repeated destroy safety;
- mapping of every ONNX status to a bounded Jarvis error code.

### Level B: native worker process

- correct manifest/auth digest;
- wrong manifest digest;
- missing/corrupted DLL;
- missing/corrupted/truncated model;
- unsupported opset/operator;
- invalid input/output metadata;
- injected runtime-load failure;
- session-create failure;
- inference failure and stall;
- output-size exhaustion;
- parent pipe closure and worker exit.

### Level C: governed adapter

Run every Level-B failure through `NativeSpeechWorkerAdapter` and the real Windows Job Object.
Require zero PID, lease and handle leakage after each case.

### Level D: soak

Run both:

1. 100 complete worker-process cycles: spawn, contain, authorize, load, infer, destroy and close.
2. 100 create/infer/destroy session cycles inside a contained worker, if the adapter supports session
   reset without weakening isolation.

The process-cycle result is authoritative for containment. The in-process cycle helps localize
runtime/session leaks.

## Acceptance gates

The tiny fixture advances only if all of the following hold:

- deterministic output matches `[0,0,1,5]` in every successful inference;
- runtime/model loading is impossible before verified Job containment;
- wrong manifest/runtime/model bytes fail before inference;
- zero surviving worker PIDs and zero leases after all failure paths;
- no parent-handle or worker-thread monotonic leak;
- post-warm-up private-memory drift <= 16 MiB;
- peak private and Job memory <= 256 MiB for the tiny fixture;
- absolute Job hard ceiling remains 640 MiB;
- p95 fixture inference <= 100 ms on the target laptop;
- p95 governed startup/session creation <= 1 second;
- no Python ML packages are imported by production runtime;
- normal runtime selection remains denied because the profile is uncertified.

The 256-MiB fixture gate is deliberately tighter than the future 512-MiB ASR target. A tiny tensor
graph exceeding it indicates runtime/configuration inefficiency that should be fixed before adding
model weights.

## Implementation order

1. Inspect and select the official ONNX Runtime CPU artifact; record metadata only.
2. Define the manifest schema and strict verifier.
3. Generate/audit the tiny fixture and pin its SHA-256.
4. Add an imported CMake target for the verified runtime under `storage`.
5. Implement the minimal C API wrapper and pure native unit contracts.
6. Implement the manifest-bound fixture worker while preserving the fake worker.
7. Add load/session/inference/teardown fault hooks restricted to the test build.
8. Extend the Python adapter with fixture authorization and typed metrics.
9. Run native, governed failure and 100-cycle soak gates.
10. Publish a certification report and ADR: advance, revise configuration or reject runtime.

## Stop conditions

Stop and investigate rather than continuing to ASR if:

- official provenance or licence cannot be pinned;
- the DLL/model path can escape approved storage roots;
- the runtime loads before authorization;
- memory exceeds 256 MiB for the tiny fixture;
- memory/handles/threads grow monotonically;
- timeout cleanup leaves a child process;
- output differs across identical inputs;
- the runtime requires Python ML dependencies in production.

## After this gate

On pass, evaluate compact Tamil/Tanglish candidates through the existing provenance-first funnel.
Start with trustworthy floating-point/native precision, five owner development files and semantic
markers. Quantization, beam search and contextual application biasing remain later ablations.

The character shell may proceed independently with synthetic presentation events, but it must not
share the heavy-worker slot or alter this inference gate.

