# MMS Tamil development benchmark v1

Date: 15 October 2026

## Outcome

The pinned `facebook/mms-tts-tam` candidate synthesized all 12 development prompts
successfully through the resident offline worker. Owner listening found that it spoke
in pure Tamil rather than natural Tanglish and lacked the requested friendly
companion delivery. It is rejected as the primary Jarvis voice and retained only as a
Tamil-only technical baseline/fallback.

Evidence directory:
`storage/benchmarks/results/facebook-mms-tts-tam-e9cf59da-20261015T134427Z`

## Measurements

| Metric | Result | Phase 1 interpretation |
| --- | ---: | --- |
| Completed | 12/12 | Pass |
| Worker startup | 0.386 s | Pass after first-run warm-up |
| Mean complete-waveform synthesis | 1.782 s | Informational |
| p95 complete-waveform audio ready | 3.561 s | Not equivalent to streaming TTFA |
| p95 real-time factor | 1.208 | Misses the <=1.0 overall target |
| Peak resident memory | 578,465,792 bytes | Passes the <=2 GB target |

Language breakdown from four development prompts per group:

| Language | Mean synthesis | Worst observed RTF | Interpretation |
| --- | ---: | ---: | --- |
| Tamil | 3.183 s | 0.844 | Sustained synthesis passes the RTF gate |
| English | 0.604 s | 1.253 | Misses RTF gate; pronunciation review required |
| Mixed | 1.559 s | 1.156 | Misses RTF gate; code-switch review required |

## Startup incident

The first owner run timed out waiting 180 seconds for the initial ready event even
though model integrity passed. A direct worker probe subsequently loaded in 0.648
seconds, and the benchmark rerun loaded in 0.386 seconds. The most likely cause is a
one-time runtime/security scan or cold dependency initialization; the evidence does
not indicate corrupt model weights.

The adapter now checks for worker exit every 100 ms instead of waiting for the entire
startup timeout, includes captured stderr in timeout/exit errors and the wrapper uses
a 300-second first-run startup allowance. A regression test covers fail-fast startup
exit reporting.

## Remaining gate

No further MMS listening or held-out testing is required for primary selection. The
owner's pure-Tamil/friendly-tone finding is already disqualifying. MMS remains
restricted to attributed non-commercial use under CC-BY-NC-4.0.

Run the resumable local listening workflow with:

```powershell
.\scripts\review-mms-tamil.ps1
```

It uses Windows PCM playback, excludes held-out prompts, validates 1-5 ratings,
hash-binds every score to its WAV and stores the private owner review under
`storage/benchmarks/reviews`.
