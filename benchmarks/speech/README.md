# Speech benchmark harness

Private audio and run outputs must stay under `storage`. This directory contains only version-controlled harness code, schemas, synthetic examples and instructions.

## Manifest workflow

1. Generate the canonical manifest with `jarvis corpus-create --output storage/datasets/speech/corpus-v1.jsonl`.
2. Review the prompts and explicitly consent before recording.
3. Make the intended microphone the Windows default recording device.
4. Record with `jarvis corpus-record --manifest storage/datasets/speech/corpus-v1.jsonl --corpus-root storage/datasets/speech`.
5. Resume at a specific prompt with `--start-at ta_001`; existing recordings are skipped by default.
6. Run `jarvis corpus-validate storage/datasets/speech/corpus-v1.jsonl`.
7. Keep the 24 held-out utterances out of pronunciation and runtime tuning.

The recorder uses the built-in Windows MCI audio API, so FFmpeg, SoX and cloud services are not required. It accepts each recording only when it is mono, 16-bit PCM WAV at 16 kHz. Use `--limit 5` for a short microphone test. Use `--overwrite` only when intentionally replacing existing audio.

Normal Jarvis microphone audio is never added to this corpus automatically.

## Natural Tanglish dialogue workflow

The original `corpus-v1.jsonl` and its recordings remain unchanged. Generate the separate scenario and owner-speech manifests with:

```powershell
jarvis dialogue-corpus-create `
  --output storage/datasets/speech/dialogue-scenarios-v1.jsonl `
  --speech-output storage/datasets/speech/tanglish-owner-v2.jsonl
```

Validate them with `jarvis dialogue-corpus-validate` and `jarvis dialogue-speech-validate`. The v2 speech recorder presents a situation plus a natural example, then asks for the exact words actually spoken:

```powershell
jarvis dialogue-speech-record `
  --manifest storage/datasets/speech/tanglish-owner-v2.jsonl `
  --corpus-root storage/datasets/speech `
  --session-output storage/datasets/speech/recording-sessions/tanglish-v2-session-01.json `
  --limit 5
```

Do not tune on scenarios marked `held-out`. Dialogue lines are original pattern-derived test material, not movie transcripts.

After a pilot or rerecord, consolidate session observations against the current WAV hashes:

```powershell
jarvis dialogue-session-consolidate `
  --manifest storage/datasets/speech/tanglish-owner-v2.jsonl `
  --dialogues storage/datasets/speech/dialogue-scenarios-v1.jsonl `
  --sessions storage/datasets/speech/recording-sessions `
  --corpus-root storage/datasets/speech `
  --output storage/datasets/speech/evaluation/tanglish-v2-pilot.eval.jsonl `
  --stt-output storage/datasets/speech/evaluation/tanglish-v2-pilot.stt.jsonl
```

Run the reference-understanding smoke test with:

```powershell
jarvis dialogue-semantic-evaluate `
  --evaluation storage/datasets/speech/evaluation/tanglish-v2-pilot.eval.jsonl `
  --dialogues storage/datasets/speech/dialogue-scenarios-v1.jsonl `
  --output-dir storage/benchmarks/results/tanglish-v2-reference-semantic-pilot
```

To score an STT run, add `--transcripts <run>/samples.jsonl`. Null or missing hypotheses become semantic failures; they never fall back to the owner reference.

