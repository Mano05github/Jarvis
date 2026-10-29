# Governed native speech-worker certification

Date: 2026-10-28  
Status: passed for deterministic fake backend  
Scope: Windows Job Object containment, central lease lifecycle, protocol failure cleanup and
resource drift. This is not ASR accuracy or real-model certification.

## Command

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test-native-speech-runtime.ps1
```

## Results

- Native memory contract: 47 checks passed.
- Native engine contract: 63 checks passed.
- Native protocol contract: 174 checks passed.
- Standalone child-process contract: 3,605 checks across 100 lifecycles passed.
- Governed adapter certification: 747 checks across 100 contained lifecycles passed.
- Governed startup p95: 47.0 ms.
- Governed maximum-response-latency p95: 16.0 ms.
- Peak observed private memory: 843,776 bytes (about 0.80 MiB).
- Peak Windows Job memory: 942,080 bytes (about 0.90 MiB).
- Surviving worker PIDs: zero.
- Active central memory leases after terminal paths: zero.
- Parent handle growth: within the four-handle test tolerance.
- First-ten versus last-ten median private-memory drift: below 16 MiB.

## Failure matrix

The governed adapter was tested with real capped Windows Job Objects against:

- exit before bootstrap;
- exit after bootstrap;
- backend-load failure;
- stall after bootstrap and before authorization completion;
- exit during audio processing;
- stall during audio processing;
- stall during finalization;
- invalid UTF-8 partial output;
- cancellation while ready and while listening.

Every case terminated the worker and released its provisional `native-stt-candidate` lease. Normal
runtime admission of that uncertified profile remains denied.

## Security invariant demonstrated

The adapter performs this sequence:

1. acquire the provisional lease;
2. spawn the backend-unloaded worker;
3. validate its bootstrap PID/session/nonce;
4. assign the exact PID to the capped Job Object;
5. verify membership using Windows `IsProcessInJob`;
6. only then calculate and send `START_AUTH`.

Focused tests also show that failed membership verification prevents authorization and cleans up the
PID and lease.

## Limitations

- The worker uses a deterministic fake backend and fixed transcript text.
- The sub-1-MiB resource measurements do not predict ONNX Runtime or model memory.
- No microphone, VAD, real acoustic inference or Tanglish accuracy is covered.
- The 512-MiB profile remains uncertified for normal runtime use.

## Decision

The governed process boundary advances to the tiny pinned ONNX inference fixture. A real
Tamil/Tanglish model remains blocked until the ONNX lifecycle, provenance and semantic gates pass.

