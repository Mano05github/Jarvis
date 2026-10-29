# Natural Tanglish v2 pilot

Updated: 10 October 2026

## Outcome

The five-file pipeline is operational and cleanly isolates the current bottleneck. The deterministic Tanglish understanding layer interprets all five owner references correctly, including correction, contextual reference and confirmation. All three generic Whisper diagnostics preserve zero of five semantic intents. Phase 1 therefore moves to a Tamil/code-switch-specialized STT candidate; further bulk recording remains paused.

This is a pipeline feasibility result, not an accuracy certification. Five development recordings are too few for model selection.

## Data integrity

- Five current WAVs were bound to their actual spoken references and SHA-256 values.
- Two recording sessions were inspected.
- The superseded `tg_004` observation was rejected because its frame count did not match the current WAV.
- The rerecorded `tg_004` session was selected without deleting either annotation file.
- Future rerecords archive the previous canonical WAV under `storage/datasets/speech/revisions/<utterance_id>` before atomic replacement.

Generated manifests:

- `storage/datasets/speech/evaluation/tanglish-v2-pilot.eval.jsonl`: semantic expectations, provenance and hashes.
- `storage/datasets/speech/evaluation/tanglish-v2-pilot.stt.jsonl`: compatibility manifest for the existing STT harness.

## Reference-understanding smoke test

Using the owner's actual typed references rather than STT hypotheses:

| Metric | Result |
|---|---:|
| Strict semantic success | 5/5 |
| Intent accuracy | 100% |
| Dialogue-act accuracy | 100% |
| Required-slot accuracy | 100% |
| Required-referent accuracy | 100% |
| Critical-marker preservation | 100% |
| Policy accuracy | 100% |

The parser correctly distinguishes `illa vendam, VS Code open pannu` as a correction with a replacement command rather than treating the entire utterance as cancellation. Confirmation is bound to a specific pending operation and expires after the next expected owner turn.

## Generic Whisper diagnostic

All runs used the resident loopback-only whisper.cpp server, four CPU threads and the five unnormalized owner WAVs.

| Profile | Exact | Mean WER | Mean CER | p95 RTF | Peak RSS | Semantic intents |
|---|---:|---:|---:|---:|---:|---:|
| Base Q5, auto language | 0% | 1.04 | 0.826 | 1.50 | ~185 MiB | 0/5 |
| Small Q5, auto language | 0% | 1.37 | 0.785 | 12.18 | ~405 MiB | 0/5 |
| Small Q5, forced Tamil | 0% | 2.06 | 0.871 | 4.65 | ~385 MiB | 0/5 |

The semantic evaluator predicted `unknown` for every hypothesis. Required correction/negation and confirmation markers were not preserved. Forced Tamil did not repair the problem, so automatic language detection is not the principal cause. Small Q5 is also outside the target real-time budget on this CPU.

Run artifacts remain private under `storage/benchmarks/results` in the directories beginning:

- `whisper-base-q5_0-tanglish5-auto-`
- `whisper-small-q5_0-tanglish5-auto-`
- `whisper-small-q5_0-tanglish5-ta-`

## Decision

1. Keep Base and Small generic Whisper only as regression baselines.
2. Do not attempt to compensate for these hypotheses with an LLM; the acoustic output has lost command anchors and safety markers.
3. The pinned Tamil-fine-tuned Whisper source was tested and rejected by the follow-up gate; see `deliverables/reports/tanglish-specialized-stt-gate.md`.
4. Require semantic intent, entity, negation and contextual-reference evidence in addition to WER.
5. Keep `tg_006` onward and all held-out scenarios unrecorded until the next multilingual/code-switch candidate crosses the five-file semantic gate.
