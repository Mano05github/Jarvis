# Evidence-backed next milestone: governed native STT feasibility gate

Date: 2026-10-24  
Status: in progress; governed fake-worker certification passed, tiny ONNX fixture next  
Primary constraint: natural Tamil-English commands on the target Windows laptop without
starving other applications or allowing uncertain speech to become authority.

The concrete failure-containment, supervisor and parallel character-shell execution plan is
[native-stt-containment-and-character-plan-2026-10-26.md](native-stt-containment-and-character-plan-2026-10-26.md).

## Decision

The next milestone is **not** "make Whisper run" or "declare a Tamil model production-ready." It is:

> Build and certify an isolated, governed native speech-worker path, then use it to make a
> reproducible go/no-go decision on real Tamil-English ASR candidates.

The milestone succeeds even if every current model is rejected, provided the result is reproducible
and identifies whether the blocker is accuracy, code-switch coverage, memory, latency, licensing,
or runtime compatibility. Large-v3-turbo remains a regression baseline. Generic Whisper scaling is
closed because larger models already consumed more resources without preserving Jarvis's app names,
references, and safety markers.

## Implementation progress (2026-10-24)

Implementation-order item 1 is complete. `Jarvis.SpeechRuntime` now has a dependency-free C
protocol module with a 40-byte little-endian header, 128-bit session ID, 64-bit sequence number,
strict message-specific payload ceilings, caller-owned storage, and no parser heap allocation.
The incremental parser handles fragmented and coalesced frames, validates strict UTF-8 for text,
rejects malformed version/header/type/flags/session/sequence fields, and remains faulted after a
bad frame until explicitly reinitialized.

Implementation-order item 2 is also complete. A Windows child executable now reserves standard
input/output for framed binary protocol, emits its PID/session/random nonce before backend load,
and requires a session-bound SHA-256 `START_AUTH` response before initializing the deterministic
fake backend.

Implementation-order item 3 is complete at the standalone child-process boundary. The Release
suite passes 47 memory-ledger checks, 63 engine-ABI checks, 174 protocol checks, and 3,605
child-process checks across 100 full lifecycles. It now covers fragmented/coalesced input,
malformed/auth/state rejection, maximum audio, broken pipes, injected early exit/load failure/audio
exit/audio stall/invalid UTF-8, zero surviving PIDs, bounded parent handles, and a 64-MiB ceiling for
the fake worker. This proves bounded parsing and standalone failure cleanup; it does **not** yet
prove the complete supervised soak, a real ONNX adapter, Tanglish accuracy, latency, or the
512-MiB certification target. Item 4 is complete: the disabled-by-default `native-stt-candidate`
profile reserves 512 MiB with 640-MiB process/job hard ceilings. The first item-5 increment is also
complete: a governed adapter verifies the assigned PID with Windows `IsProcessInJob` before sending
`START_AUTH`, and focused exit/stall/invalid-output tests release the PID and central lease.
The complete governed gate now passes 747 checks across 100 contained lifecycles with zero surviving PIDs or
leases. Startup p95 was 47.0 ms, maximum-response-latency p95 was 16.0 ms, peak private memory was
843,776 bytes and peak Job memory was 942,080 bytes. The next task is the pinned tiny ONNX adapter
proof; these fake-backend memory results must not be extrapolated to a real runtime or model.

## Why this is the correct milestone

Jarvis already has a tested memory governor and Job Object supervisor, a startup-gated worker
pattern, a dependency-free C memory ledger, a versioned C ASR lifecycle contract, and a deterministic
intent/slot safety gate. The missing link is the isolated process boundary between PCM audio and a
real native inference runtime. Adding another model directly to Python would bypass the strongest
work already completed and make memory/crash behaviour harder to certify.

## Evidence ledger

Sources were checked live on 2026-10-23/24. A source proves only the claim listed here; results from
English, Mandarin, or generic corpora are not treated as proof of Tanglish quality.

| Evidence | What it supports | Important limitation |
|---|---|---|
| [Conformer, arXiv 2005.08100](https://arxiv.org/abs/2005.08100) | Combining convolutional local features and transformer global context is effective and can be parameter-efficient; the paper reports a 10M-parameter small model. | Does not prove Tamil-English accuracy, streaming latency, or Windows memory. |
| [Emformer, arXiv 2010.10759](https://arxiv.org/abs/2010.10759) | Bounded memory banks, cached keys/values, and block processing support low-latency streaming. | No licensed Tamil-English checkpoint is supplied for Jarvis. |
| [Zipformer, arXiv 2310.11230](https://arxiv.org/abs/2310.11230) | Lower frame rates in middle stacks and reused attention weights target faster, more memory-efficient ASR. | Reported corpora are not Tanglish. |
| [FastConformer, arXiv 2305.05084](https://arxiv.org/abs/2305.05084) | Downsampling and limited-context attention reduce inference cost; the paper reports 2.8x speedup over original Conformer. | A large checkpoint may still violate Jarvis's RAM target. |
| [MUCS 2021, arXiv 2104.00235, Interspeech DOI 10.21437/Interspeech.2021-1339](https://arxiv.org/abs/2104.00235) | Indian-language ASR is low-resource and code-switching needs explicit evaluation. | Tamil is in the multilingual task, but its code-switch pairs are Hindi-English and Bengali-English, not Tamil-English. |
| [Tamil-English synthetic code-switch study, arXiv 2506.14177](https://arxiv.org/abs/2506.14177) | Phrase-level synthetic mixing improved code-switch training and explicitly includes TA-EN. | Its TA-EN test is described as synthetic sentence-mixed speech and its models are large; real owner-recorded Tanglish remains mandatory. |
| [Streaming transducer distillation, arXiv 2409.13499](https://arxiv.org/abs/2409.13499) | A future compact streaming transducer can be trained using filtered pseudo-labels; it studies chunk decoding, n-gram fusion, and entity biasing. | It is a training direction, not a ready Tamil-English model. |
| [Adaptive contextual biasing, arXiv 2306.00804](https://arxiv.org/abs/2306.00804) | Context can improve rare words, but always-on high bias can degrade common-word recognition; adaptive activation reduces that damage. | Bias is not permission to replace acoustically unsupported words with app names. |
| [SLURP, arXiv 2011.13205](https://arxiv.org/abs/2011.13205) | Voice-assistant evaluation needs intent and entity/slot analysis, not WER alone. | Jarvis must establish its own Tamil/Tanglish thresholds. |
| [Integer-only quantization, arXiv 1712.05877](https://arxiv.org/abs/1712.05877) | Integer inference can improve the on-device accuracy/latency trade-off when quantization is co-designed. | Post-training INT8 is not automatically lossless for ASR. |
| [ONNX Runtime quantization docs](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html) | Dynamic quantization is generally recommended for transformer/RNN models; S8S8 QDQ is the default CPU choice; tensor-level debugging is available. | INT8 should not precede Jarvis's FP semantic gate. |
| [ONNX Runtime repository](https://github.com/microsoft/onnxruntime) | MIT native runtime with C API, thread limits, CPU-arena control, and arena `max_mem`. | Arena limits are not a whole-process hard cap; Job Objects remain necessary. |
| [sherpa-onnx repository](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 native runtime supporting online/offline ASR and C/C++ integration. | Runtime licence does not license model weights. |
| [sherpa-onnx hotword docs](https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html) | Transducer hotwords use Aho-Corasick; partial-path boosts are cancelled on mismatch. | The official pretrained-model index had no Tamil occurrence when checked. |
| [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) and [extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information) | OS-enforced job/process commit limits, peak accounting, child containment, and termination. | Does not improve model accuracy or allocator efficiency. |
| Hugging Face API metadata for `ai4bharat/indic-conformer-600m-multilingual` | Revision `2a77d305038dfc502fd9464e7d028b90381976cb`, MIT tag, gated access, ONNX assets, approximately 2.381 GiB across 404 files. | Cannot plausibly meet a sub-512-MiB worker target; no natural Tanglish proof. |
| Hugging Face API metadata for `ai4bharat/indicconformer_stt_ta_hybrid_ctc_rnnt_large` | Revision `8c31aa8d04964b8fc87e4eaaee7916f7d2c024da`, MIT tag, gated access, Tamil tag, 523,192,320-byte NeMo checkpoint. | No English entity, ONNX compatibility, or sub-512-MiB proof. |
| [Distil-Whisper, arXiv 2311.00430](https://arxiv.org/abs/2311.00430) and public model metadata | Distillation can reduce parameters and increase speed. | The public `distil-whisper/distil-large-v3` model card is English-only. |

### Candidate conclusion

No verified source currently establishes a compact, public, licensed, streaming Tamil-English model
that meets Jarvis's target. Therefore:

1. `sherpa-onnx` is an eligible runtime, not an eligible model by itself.
2. AI4Bharat IndicConformer models are legitimate controls, not pre-certified production candidates.
3. Unlicensed community conversions or models without immutable provenance are inadmissible.
4. If no pretrained model passes, training/distillation becomes a later milestone rather than being
   smuggled into this feasibility milestone.

## Target architecture

```text
Microphone / WAV fixture
        |
Python controller + deterministic memory lease
        |
PID assigned to capped Windows Job Object before model load
        |
Native worker: bounded protocol + C memory ledger + C engine ABI
        |
Pinned ONNX Runtime or sherpa-onnx model adapter
        |
n-best text + acoustic scores + latency/memory evidence
        |
Adaptive catalog bias / constrained entity evidence
        |
Deterministic intent-slot safety gate
        |
proposal, clarification, or rejection (never direct execution)
```

The model never calls the broker and never decides an action happened. Speech produces evidence;
the compiler, approvals, and broker remain the only action path.

## Work package 1: native worker protocol

Create a small C executable around the existing engine ABI. Use inherited anonymous pipes or
redirected standard handles so there is no globally discoverable speech endpoint.

Protocol v1:

- fixed magic, version, type, payload length, session ID, and sequence number;
- little-endian fixed-width integers and strict maximum sizes;
- strict PCM16 mono 16 kHz frames;
- messages: `HELLO`, `BOOTSTRAP`, `START_AUTH`, `READY`, `START_SESSION`, `AUDIO`,
  `PARTIAL`, `FINISH`, `FINAL`, `CANCEL`, `RESET`, `STATS`, `ERROR`, `SHUTDOWN`;
- no JSON parser and no shell-command field;
- stdout reserved for framed protocol; bounded diagnostics on stderr;
- unknown types, replayed sequence numbers, oversized frames, and illegal transitions fail closed.

Startup is two-stage:

1. A minimal worker starts without loading a runtime/model and reports its PID.
2. Python assigns it to the Job Object and verifies the lease.
3. Python sends a digest-bound `START_AUTH` message.
4. Only then may the worker validate the manifest and load the backend.

Contract tests cover fragmented/coalesced frames, zero/maximum/oversized payloads, replay, wrong
session/version, invalid state transitions, cancellation during every phase, backend crash, parent
exit, broken pipe, timeout, invalid UTF-8, output exhaustion, and cleanup of every PID/lease/workspace.

## Work package 2: governed Python supervisor

Extend `GovernedWorkerSlot`; do not create another process manager.

- Acquire a provisional `native-stt-candidate` lease before spawn.
- Start gated and assign the Job Object before authorizing model load.
- Allow one active speech worker and a bounded queue.
- Enforce startup, per-chunk, finalization, and idle timeouts.
- Capture peak private/job commit, working set, CPU, startup, partial/final latency, RTF,
  accepted chunk size, and exit reason.
- Never close unrelated user applications to create headroom.

Initial feasibility policy:

- certification threshold: peak private commit <= 512 MiB;
- experimental hard ceiling for a compact candidate: 640 MiB;
- protected system floor remains 4 GiB;
- maximum heavy workers remains one;
- larger accuracy controls use separately named provisional profiles and may be denied.

## Work package 3: runtime adapter proof

Do not start with the 2.381-GiB model. Prove the process/runtime boundary using a tiny deterministic
ONNX fixture.

1. Pin an exact ONNX Runtime release and record binary/source SHA-256 plus MIT licence.
2. Use the C API; production must not import Python, PyTorch, Transformers, or NeMo.
3. Set explicit intra-op/inter-op threads and arena policy.
4. Measure both allocator memory and OS commit; Job Objects remain the hard boundary.
5. Run 100 create/infer/destroy cycles and require bounded drift.

Add a sherpa-onnx adapter only after finding a compatible Tamil/Tamil-English transducer. Its native
streaming and hotwords are attractive, but adding it before a model exists creates dependency cost
without advancing accuracy.

## Work package 4: provenance-first candidate funnel

Before acquiring model bytes, require:

1. Publisher and immutable revision.
2. Weight licence, not merely repository/runtime licence.
3. Recorded gating terms; the user completes any required account acceptance.
4. Complete file inventory, total bytes, and hash plan.
5. Architecture, tokenizer/script, languages, streaming and runtime requirements.
6. Estimated precision-specific weight residency and workspace.
7. Published corpus checked for real Tamil-English code-switch speech.
8. No commercial-suitability claim from a non-commercial licence.

| Candidate | Role | Advancement rule |
|---|---|---|
| AI4Bharat Tamil hybrid CTC/RNNT large | Tamil monolingual control | Run only after legal access/export compatibility. Reject as primary if English app entities disappear. |
| AI4Bharat 600M multilingual ONNX | Accuracy/control experiment | Never certify under compact profile; the governor may safely deny it. |
| New compact streaming TA-EN transducer | Preferred production candidate | Acceptable licence, exact revision, <=350 MiB weight target, native runtime, and Tamil+English token evidence. |
| Public Distil-Whisper English model | Excluded | English-only metadata does not address Tanglish. |
| Unlicensed community conversions | Excluded | No trustworthy provenance or redistribution basis. |

## Work package 5: accuracy-first decoding

Use streaming CTC/RNNT/transducer decoding with persistent encoder state, bounded rings, and n-best
hypotheses. Do not collapse immediately to one transcript.

For application names, use bounded contextual evidence from `config/applications.toml`:

- activate app bias only in an app-related dialogue state;
- use Aho-Corasick/trie matching when supported;
- cap boosts and cancel them after partial-path mismatch;
- compare biased and unbiased/common-utterance performance;
- require acoustic/n-best margin before accepting an app entity;
- clarify when two apps are plausible or evidence is weak.

The prior Tamil Whisper hotword run worsened accuracy, so biasing must be an ablation, not a default.
Advancement depends on exact intent, required slots, safety-marker recall, hallucinations, and safe
clarification. WER/CER remain diagnostic only.

## Work package 6: quantize only after accuracy

Run the best trustworthy precision first. INT8 cannot repair absent language coverage.

If FP passes:

1. Optimize the ONNX graph separately from quantization.
2. Try dynamic INT8 for transformer/RNN-heavy sections.
3. Compare S8S8 QDQ and only then alternatives justified by measured saturation/accuracy.
4. Compare representative-data static calibration for convolution-heavy sections.
5. Calibrate on Tamil, English, Tanglish, numbers, app names, noise, silence, and corrections.
6. Use weight/activation matching to locate sensitive nodes and exclude them selectively.
7. Reject quantization if any critical marker or required slot regresses.

## Benchmark ladder and gates

### Gate A: protocol and containment

- All warning-as-error native and strict Python contracts pass.
- Malformed frames cannot allocate unbounded memory.
- Model load cannot precede Job Object assignment.
- Injected crash/timeout/cancel leaves zero PIDs and zero leases.
- 100 fake-backend sessions show no material drift.

### Gate B: existing five-file natural-Tanglish development gate

- 5/5 strict semantic success;
- every required app/reference slot preserved;
- every cancellation/confirmation/correction marker preserved;
- zero invented entities;
- held-out audio remains sealed.

A failing candidate stops before beam sweeps, biasing, quantization, or more recording.

### Gate C: one-variable ablations

For a Gate-B candidate, compare greedy/bounded beam, unbiased/adaptive app bias, native precision/INT8,
and chunk/thread settings. Store exact config, model digest, transcripts, semantic packets, latency,
RTF, CPU, memory, and failure reason.

### Gate D: expanded development and sealed held-out corpus

Only after Gate B, add balanced Tamil/English/within-utterance Tanglish; commands, corrections,
anaphora, cancellation, numbers and dates; app aliases and negative names; noise, distance, fast
speech, hesitation, silence and non-speech; multiple sessions/days and consented speakers. Freeze a
separate hash-bound held-out split before optimization.

Production-candidate thresholds:

- semantic exact accuracy >= 95%;
- required-slot recall >= 98%;
- cancellation/negation/confirmation recall = 100%;
- false action acceptance = 0;
- p95 RTF <= 1.0, target <= 0.75;
- p95 first stable partial <= 400 ms;
- p95 final short-command result <= 1.5 s after end of speech;
- peak private commit <= 512 MiB;
- zero orphans/leaked leases in 100 sessions;
- no monotonic memory growth greater than 16 MiB after warm-up.

Only a passing held-out run may set `certified = true`.

## If no pretrained model passes

Do not weaken the gate. Open a separate training milestone:

1. Obtain properly consented natural Tamil-English development speech.
2. Use phrase-mixed synthetic audio as augmentation, never the sole test distribution.
3. Use the best legal multilingual teacher and filter pseudo-labels by confidence, agreement,
   hallucination, and semantic markers.
4. Train/distill a small streaming transducer or Zipformer/Conformer.
5. Keep real owner-recorded Tanglish for development and sealed evaluation.
6. Quantize only after the FP student passes semantics.

The 2025 TA-EN synthetic-data paper and 2024 streaming-distillation paper justify this research
direction but do not eliminate real Tanglish evaluation. Until local STT is certified, safe fallbacks
are typed input and an explicitly configured privacy-approved remote STT route.

## Implementation order

1. Define bounded protocol header/parser.
2. Build native fake-backend worker.
3. Add malformed-frame, replay, cancellation, crash, and cleanup contracts.
4. Connect `GovernedWorkerSlot` with pre-load Job Object assignment.
5. Add provisional `native-stt-candidate` memory profile.
6. Prove the adapter using a tiny pinned ONNX fixture.
7. Add machine-readable provenance/licence inspectors.
8. Run metadata-only candidate triage.
9. Acquire a gated candidate only after required user terms/token action.
10. Run Gate B once with the pinned build.
11. Only on pass, run bias, beam, chunk, and INT8 ablations.
12. Expand/freeze the corpus and run held-out certification.
13. Record an ADR: certify, retain as control/teacher, or reject.

## Completion definition

The milestone is complete when:

- a real child worker is contained before runtime/model load;
- the protocol/failure matrix passes;
- a tiny real ONNX inference proves the adapter without Python ML dependencies;
- provenance/licence evidence is pinned and machine-readable;
- at least one legally accessible model receives a reproducible Gate-B decision, or the governor
  records a reproducible admission denial;
- neither the 4-GiB floor nor semantic gate is weakened;
- no uncertified model is enabled in normal Jarvis runtime.

## Explicitly out of scope

- real desktop execution;
- TTS or public-figure voice cloning;
- broad microphone UX polish;
- training a new ASR model from scratch;
- certification on development data alone;
- closing user applications to obtain RAM.

