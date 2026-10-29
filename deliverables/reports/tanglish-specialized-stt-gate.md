# Tanglish specialized-STT gate

Updated: 11 October 2026

## Decision

`vasista22/whisper-tamil-small` is rejected as Jarvis's primary Phase-1 STT. It remains a reproducible research baseline, but it must not drive commands. The model recognizes some Tamil meaning while repeatedly deleting the English entities that determine what Jarvis should operate on.

This result does not show that the dialogue or LLM layer is unnecessary or broken. After dual-script normalization, the understanding layer correctly accepts the one complete meaning retained by STT. It cannot safely reconstruct application names, replacement commands or locations that are absent from the transcript.

## Reproducible setup

- Source: `vasista22/whisper-tamil-small`
- Revision: `ac0d71cd70d4c66aec7126996cd9e56e97e698b7`
- Source weight: 967,099,139 bytes, SHA-256 `8bad6eccfd11ec5b41a9116e41845d8ecd92fe1c1236cc916a082d0a2ce402d0`
- Conversion: CTranslate2 4.8.2 INT8
- Runtime: faster-whisper 1.2.1, Python 3.12.10, four CPU threads
- Decoder: beam size 5, temperature 0, no VAD, no cross-utterance conditioning
- Evidence: five owner-recorded development utterances; held-out data was not opened
- Audio control: raw recordings plus non-destructive normalization to approximately -22 dBFS
- Scoring: WER/CER plus intent, slots, referents, policy and safety-marker preservation

The conversion manifest is private under `storage/models/stt/ctranslate2/vasista22-whisper-tamil-small-ac0d71cd-int8`. Interrupted conversion directories are automatically removed only after a valid canonical model and manifest exist.

## Results

The normalized control changed median level by +12.25 dB with zero clipped samples. It improved WER slightly, but did not restore the missing command entities.

| Normalized profile | Exact | Mean WER | Mean CER | p95 RTF | Peak process-tree RSS | Strict semantics |
|---|---:|---:|---:|---:|---:|---:|
| Forced Tamil | 0% | 1.067 | 0.899 | 1.80 | ~477 MiB | 1/5 |
| Auto language | 0% | 1.067 | 0.899 | 3.47 | ~478 MiB | 1/5 |
| Forced Tamil + domain hotwords | 0% | 1.325 | 0.949 | 2.36 | ~500 MiB | 0/5 |

Dual-script semantic scoring for the unbiased normalized run:

- Intent and dialogue-act accuracy: 20%
- Required-slot accuracy: 0/4
- Required-referent accuracy: 1/3
- Safety-marker preservation: 1/2
- Strict semantic success: 1/5

## What the transcripts prove

| Utterance purpose | Retained evidence | Decisive loss | Safe outcome |
|---|---|---|---|
| Open Notepad | unrelated Tamil phrase | `Jarvis`, `Notepad`, `open` | reject/clarify |
| Correct to VS Code | `வேண்டாம்` (negation/cancel) | `VS Code`, replacement `open` | do not execute either app command |
| Close previous app | Tamil rendering of `close` | previous-app reference | clarify target |
| Confirm clarification | `ஆமா ஆமா` (yes) | none needed in bound context | accepted; the only strict pass |
| Show latest downloads | latest/files meaning | `download` location | clarify location |

The hotword control is also rejected. It returned three empty transcripts, worsened WER and did not produce a safe command. Domain bias may be reconsidered only with a different multilingual acoustic model and explicit false-positive tests.

## Next gate

1. Keep generic Whisper and this Tamil fine-tune as regression baselines only.
2. Benchmark a stronger multilingual/code-switch model on the same five development files before collecting more owner speech.
3. Use a high-capacity multilingual model first as an accuracy ceiling; latency is measured but is not the first acceptance criterion for that diagnostic.
4. Accept a candidate only if it preserves English entities, Tamil control words, correction/negation and contextual references. WER alone cannot pass it.
5. If no compatible pretrained model crosses the five-file semantic gate, move to a two-pass architecture: multilingual ASR plus constrained entity recovery from Jarvis's local app/file catalog, with clarification whenever the entity evidence is ambiguous.
6. Keep `tg_006` onward and held-out scenarios unopened until this next model gate is reviewed.

