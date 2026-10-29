# Jarvis native speech runtime foundation

This dependency-free C library is the memory-control boundary for future local
ASR engines. It does not contain a model implementation and cannot transcribe
audio yet. Its deterministic fake backend and child worker exist only to verify
the host and process contracts.

It provides:

- separate private-commit and physical-working-set budgets;
- per-resource and per-phase peak accounting;
- overflow-safe reserve/release operations;
- monotonic binary search for the largest safe streaming frame chunk;
- a caller-owned fixed bump arena with no hidden heap growth;
- a versioned, engine-neutral streaming ASR ABI;
- strict PCM16 mono 16 kHz input validation;
- enforced ready/listening/finished/cancelled/faulted lifecycle states;
- bounded caller-owned transcript results, cancellation, and reset;
- memory admission and temporary-workspace release around every chunk;
- a fixed 40-byte little-endian worker-protocol header;
- hard per-message payload limits with no parser heap allocation;
- incremental fragmented/coalesced-frame parsing with fail-closed faults;
- strict UTF-8, session-ID, and monotonic-sequence validation;
- a binary-stdio fake worker that starts without loading its backend;
- random bootstrap session/nonce generation and challenge-bound start authorization.

Mapped model weights should normally charge physical residency but not private
commit. Engine-owned decoded or transformed weights charge both. The worker
must acquire the existing Python memory-governor lease and Windows Job Object
before invoking a future ONNX/sherpa-onnx adapter. A model runtime must stay in
that capped worker process rather than being linked into the trusted controller.

Run the native contract tests with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test-native-speech-runtime.ps1
```

The current contracts cover 47 memory checks, 63 engine checks, 174 protocol
checks, and 3,605 interactive child-process checks across a 100-lifecycle soak.
The process matrix includes malformed/auth/state failures, fragmented and
coalesced input, maximum audio, broken pipes, injected exit/stall/load failure,
invalid UTF-8, PID cleanup, parent-handle cleanup, and a 64-MiB fake-worker
private-memory ceiling. This foundation still cannot transcribe audio. The next
increment connects the child to the governed Python supervisor and Windows Job
Object so containment is verified before start authorization. That first adapter
increment is now implemented in `src/jarvis/runtime/native_speech.py`; the next
gate repeats the complete failure matrix and 100-cycle soak through the governed
adapter rather than the standalone process harness. That governed gate now passes
747 checks across 100 contained lifecycles. The next increment is a tiny pinned
ONNX fixture inside the same worker boundary.

The fake worker emits a 40-byte `BOOTSTRAP` payload containing its PID,
capabilities, and a random 32-byte nonce. It will not initialize even the fake
backend until it receives `START_AUTH` containing
`SHA-256("jarvis-stt-start-auth-v1" + session_id + nonce)`. The future supervisor
must answer only after assigning and verifying the child in its capped Job Object.
