# MMS phonetic Tanglish stopgap v1

Date: 15 October 2026

## Outcome

The Tamil MMS model's vocabulary contains almost no usable Latin alphabet coverage,
which explains why English words disappeared or sounded like pure Tamil. A strict,
editable pronunciation layer now converts reviewed English phrases into Tamil-script
phonetic spellings before synthesis. Unknown Latin words fail explicitly instead of
being silently dropped.

The four mixed-language development prompts synthesized successfully under run:
`storage/benchmarks/results/mms-tanglish-stopgap-e9cf59da-20261015T181547Z`.

| Metric | Result |
| --- | ---: |
| Completed | 4/4 |
| Worker startup | 0.493 s |
| Mean complete-waveform synthesis | 3.592 s |
| p95 complete-waveform audio ready | 4.583 s |
| p95 real-time factor | 1.007 |
| Peak resident memory | 581,095,424 bytes |

The profile uses speaking rate `0.92`, noise scale `0.60` and duration noise `0.75`
for a slightly slower, steadier delivery. This is bounded prosody tuning, not true
friendly/emotional conditioning. The fixed MMS speaker remains a stopgap and cannot
become the requested final cinematic assistant voice.

## Safety and limitations

- The lexicon is `config/tts/mms-tanglish-pronunciation-v1.toml` and uses longest,
  case-insensitive phrase matching.
- Any unmapped Latin term stops synthesis with the exact unknown terms listed.
- The approach produces Tamil-accented English loanwords in one consistent voice; it
  does not provide native English pronunciation or open-domain Romanized-Tamil
  coverage.
- MMS remains CC-BY-NC-4.0 and is suitable only for attributed non-commercial use.

## Owner check

Run:

```powershell
.\scripts\review-mms-tamil.ps1 `
  -RunId mms-tanglish-stopgap-e9cf59da-20261015T181547Z `
  -Language mixed
```

This plays and records scores for exactly the four development samples. Held-out
prompts remain untouched.

## Owner review result

Completed: 16 October 2026 (Asia/Calcutta)

| Metric | Result |
| --- | ---: |
| Accepted samples | 2/4 (50%) |
| Mean intelligibility | 3.50/5 |
| Mean pronunciation | 3.50/5 |
| Mean naturalness | 3.00/5 |
| Mean Jarvis voice fit | 3.25/5 |
| Identity distinctness | 4/4 pass |

The conversational sample was rejected as robotic despite 4/5 intelligibility and
pronunciation. The command sample scored 1/5 on every quality dimension. Technical
and number/date samples passed at 4/5 and 5/5 respectively.

Decision: reject the phonetic-MMS stopgap as a general Jarvis voice. Do not integrate
it into conversation or command acknowledgement, and do not open the held-out set.
The two accepted samples remain pronunciation evidence only; phrase-specific success
does not justify a dynamic runtime voice.
