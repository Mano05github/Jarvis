# STT challenger compatibility probe

Generated: 2026-10-10T12:37:49.2619082+00:00

Python: 3.12.10  
Platform: x86_64-pc-windows-msvc

## Model metadata

| Repository | Status | Revision | License | Gated | Known bytes | Library |
|---|---|---|---|---|---:|---|
| ai4bharat/indicconformer_stt_ta_hybrid_ctc_rnnt_large | failed | - | - | - | - | The remote server returned an error: (401) Unauthorized. |
| vasista22/whisper-tamil-small | failed | - | - | - | - | The remote server returned an error: (401) Unauthorized. |
| Systran/faster-whisper-small | failed | - | - | - | - | The remote server returned an error: (401) Unauthorized. |

## Windows Python 3.12 wheel-only resolution

| Probe | Requirement | Result | Exit code |
|---|---|---|---:|
| nemo-asr | nemo_toolkit[asr] | failed | 1 |
| faster-whisper | faster-whisper | passed | 0 |
| onnxruntime | onnxruntime | passed | 0 |

Full API responses, file hashes/sizes and resolver output are stored in storage/models/stt/candidate-probes.

This probe does not install packages or download model weights. A passing resolver result is necessary but not sufficient for certification.
