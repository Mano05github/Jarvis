# Whisper Large-v3-turbo Tanglish gate

Updated: 11 October 2026

## Purpose

Evaluate official `openai/whisper-large-v3-turbo` as the first multilingual/code-switch accuracy ceiling after generic Whisper Base/Small and a Tamil-only fine-tune failed to preserve English command entities.

Pinned source revision: `41f01f3fe87f28c78e2fbf8b568835947dd65ed9`.

## Method

1. Inspect the pinned Git source with Git LFS smudging disabled.
2. Record the declared license, file inventory, LFS byte counts and LFS SHA-256 identities.
3. Download only the SafeTensors model and required tokenizer/config files.
4. Convert locally to CTranslate2 INT8 using the project-local Python 3.12.10 runtime.
5. Run the five natural owner-Tanglish development files in forced-Tamil and automatic-language modes without prompts or hotwords.
6. Use normalized audio for the primary comparison and raw audio only as a controlled follow-up.
7. Score semantic intent, required entities, correction/negation, confirmation and contextual references. WER/CER remain diagnostic.

Primary decoding uses beam size 5, temperature zero, no VAD and no previous-text conditioning. Segment-level probability evidence is retained. Word-level timestamp alignment is optional because the evidence smoke test showed that it materially increases latency and can alter segmentation on this CPU.

## Five-file gate

- `tg_001`: retain Notepad and open.
- `tg_002`: retain correction/negation, VS Code and replacement open.
- `tg_003`: retain close and the previous-app reference.
- `tg_004`: retain affirmative confirmation.
- `tg_005`: retain latest, downloads and files.

No missing entity may be guessed. The preferred advancement result is 5/5 strict semantic success, all required slots and all safety markers, with zero ungrounded entities. Accuracy is evaluated before latency optimisation.

## Result

Large-v3-turbo is rejected as Jarvis's primary STT.

| Profile | Mean WER | Mean CER | p95 RTF | Peak RSS | Strict semantics |
|---|---:|---:|---:|---:|---:|
| Normalized, forced Tamil | 2.047 | 0.884 | 7.21 | ~1.09 GiB | 0/5 |
| Normalized, auto language | 1.967 | 0.889 | 19.88 | ~1.09 GiB | 0/5 |
| Raw, forced Tamil | 2.497 | 1.298 | 8.44 | ~1.09 GiB | 0/5 |

The raw control is worse, proving normalization did not cause the failure. Automatic language selection misclassified owner speech as Spanish and Icelandic on two samples. Forced Tamil partially retained open/close and latest/download concepts, but lost Notepad, VS Code, the previous-app referent and confirmation. It cannot safely drive commands.

No hotword, beam or thread sweep is justified. Official full Whisper Large-v3 is the final Whisper-family accuracy control because its decoder is substantially deeper than Turbo. Only forced-Tamil, normalized, beam-5 decoding will be evaluated; latency is diagnostic.

## Reproducible Turbo commands

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\inspect-whisper-large-v3-turbo-source.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\acquire-whisper-large-v3-turbo.ps1 `
  -SkipDependencyInstall

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\benchmark-whisper-large-v3-turbo.ps1
```

All large files remain under `storage`. Architecture v1.4 resumes the Qwen/Tanglish track as a controlled semantic-decoder experiment: STT remains untrusted evidence, Qwen may select only evidence-linked candidates, and absent critical entities must clarify rather than be reconstructed as fact.

## Full Large-v3 accuracy control

Pinned official revision: `06f233fe06e710322aca913c1bc4249a0d71fce1`.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\inspect-whisper-large-v3-source.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\acquire-whisper-large-v3.ps1 `
  -SkipDependencyInstall

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\benchmark-whisper-large-v3.ps1
```

Result: full Large-v3 is also rejected as a primary command engine. It achieved 1/5 strict semantic success, 0/4 required slots, p95 real-time factor 12.77 and approximately 2.15 GiB peak RSS. The one success preserved an affirmation; application entities and contextual action meaning remained unreliable. Further generic Whisper scaling is closed unless materially new evidence appears.

