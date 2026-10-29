# STT challenger selection

Updated: 10 October 2026

## Compatibility evidence

- Native Windows/Python 3.12 `nemo_toolkit[asr]` wheel-only resolution fails. The resolver identifies missing usable wheels across dependencies including `wget`, `pynini`, `antlr4-python3-runtime` and related Hydra constraints.
- `faster-whisper` resolves successfully with CTranslate2 4.8.2 on the target platform.
- ONNX Runtime resolves successfully on the target platform.
- The AI4Bharat repository requires authentication or gating, and its required native NeMo stack already fails the runtime gate. It is not the first implementation candidate.

## Evaluated candidate

Tamil-fine-tuned Whisper through CTranslate2 INT8 passed source, license and runtime compatibility checks, but failed the natural-Tanglish semantic gate.

- Model repository: `vasista22/whisper-tamil-small`
- Pinned revision: `ac0d71cd70d4c66aec7126996cd9e56e97e698b7`
- Runtime: `faster-whisper` / CTranslate2 INT8 on CPU
- Reason: this changes both the Tamil-specific weights and the CPU runtime, unlike generic `faster-whisper`, which would address speed only.

## Acquisition and evaluation gate

Source inspection passed: Apache-2.0, pinned revision `ac0d71cd70d4c66aec7126996cd9e56e97e698b7`, and PyTorch weight identity `8bad6eccfd11ec5b41a9116e41845d8ecd92fe1c1236cc916a082d0a2ce402d0` at 967,099,139 bytes.

`scripts/acquire-tamil-whisper.ps1` downloads only the pinned PyTorch weights, verifies size and SHA-256, installs conversion/runtime dependencies into an isolated project-local environment, and creates a CTranslate2 INT8 model. It does not download the redundant Flax weights.

`scripts/benchmark-tamil-whisper.ps1` runs resident CPU INT8 benchmarks in forced-Tamil and automatic-language modes, then applies the same semantic gate used for the rejected generic Whisper profiles.

Acquisition and conversion completed successfully. On the normalized five-file pilot, forced Tamil produced 1.067 WER, 1.80 p95 RTF, about 477 MiB process-tree RSS and only 1/5 strict semantic success. It preserved 0/4 required slots. Auto-language decoding was slower with identical text accuracy. Domain hotwords worsened the result.

Decision: retain the model only as a pinned regression baseline. The next challenger must be multilingual/code-switch capable rather than Tamil-only. Full evidence is in `deliverables/reports/tanglish-specialized-stt-gate.md`.
