# STT challenger gate

Updated: 10 October 2026

## Decision

The current generic Whisper Base/Small multilingual profiles are rejected as primary Tamil STT candidates on `mano_pc`.

Ten calibrated Tamil recordings were normalized non-destructively and decoded with an explicit Tamil language setting through a resident whisper.cpp server:

| Profile | Exact match | Mean WER | p95 RTF | Peak RSS |
|---|---:|---:|---:|---:|
| Base Q5_0 | 0% | 0.885 | 2.51 | 193,531,904 bytes |
| Small Q5_0 | 0% | 0.873 | 16.79 | 424,964,096 bytes |
| Small F16 | 0% | 0.870 | 24.03 | 741,732,352 bytes |

The F16 control proves Q5 quantization is not the material accuracy cause. `faster-whisper` with the same generic Whisper weights may improve runtime but is not an accuracy challenger and must not be treated as one.

## Next candidate order

1. A Tamil-specialized local model, led by AI4Bharat IndicConformer Tamil if its exact model license, Windows/Python 3.12 runtime and offline CPU resource use pass review.
2. A Tamil-fine-tuned Whisper model converted to CTranslate2 INT8 only if it has verifiable provenance and the generic-weight comparison is retained as evidence.
3. A compact ONNX Tamil model if the above candidates cannot satisfy the 2 GB memory and offline Windows gates.

## Acquisition gate

Do not download or execute remote model code until all of the following are recorded:

- exact repository and immutable revision;
- license for weights and code;
- expected download and installed sizes;
- SHA-256 or immutable snapshot identity;
- whether `trust_remote_code` is required;
- Python 3.12 and native Windows support;
- CPU-only inference path and quantization format;
- local-only cache/output locations under `storage`.

Raw owner audio stays local and must not be uploaded during candidate evaluation.
