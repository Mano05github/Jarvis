# TTS prototype readiness v1

Updated: 13 October 2026

## Current result

The first offline candidate path has synthesized real development audio. Jarvis has
a supervised resident-worker adapter for Tamil MMS VITS, a CLI benchmark entry point
and a balanced 24-prompt original evaluation pack. The supplied film clip is not used
by this path.

The adapter keeps the model loaded across prompts, forces Hugging Face offline mode,
uses bounded startup/request timeouts, validates the returned output path and records
wall time, real-time factor, CPU time and process-tree peak RSS. Reports distinguish
model startup from complete-waveform audio-ready latency. MMS VITS is non-streaming,
so this profile does not claim true time-to-first-audio.

## Candidate gate

| Candidate | Runtime status | Model status | Decision status |
| --- | --- | --- | --- |
| Facebook MMS Tamil VITS | Resident CPU worker implemented and unit-tested | Hash-verified source at `e9cf59da`; CC-BY-NC-4.0; development run completed 12/12 | Rejected as primary: pure Tamil/fixed delivery; fallback baseline only |
| AI4Bharat IndicF5 | GitHub source pinned; CPU/expressive path exists, but no code license or English/Tanglish evidence; model access requires credentials | Not acquired | Rejected |
| AI4Bharat Indic-TTS | MIT code; monolingual FastPitch/HiFi-GAN, no style/code-switch evidence, legacy stack | Not acquired | Rejected as primary |
| AI4Bharat Indic Parler-TTS | Description-conditioned architecture, but anonymous model access requires credentials | Not acquired | Rejected by no-token metadata gate |
| eSpeak NG Tamil | Existing bounded fallback adapter | Executable not present in project storage | Emergency intelligibility baseline only |

No candidate becomes the Jarvis production voice until its license and provenance
permit the intended local use and it passes clarity, Tanglish pronunciation, latency,
memory, cancellation and identity-distinctness review.

ADR-0010 now requires expressive code-switching for the primary voice. The canonical
original voice traits are defined in `config/tts/jarvis-voice-v1.toml`.

## Implemented evidence

- `benchmarks/speech/tts-eval-v1.jsonl`: 24 original prompts; Tamil, English and
  mixed language; conversation, command, technical and number/date categories; 12
  development and 12 held-out prompts.
- `tools/mms_vits_worker.py`: local Transformers VITS inference and atomic PCM WAV
  output.
- `src/jarvis/benchmarking/mms_vits_worker.py`: supervised resident process,
  offline-only environment, request correlation and resource measurement.
- `jarvis tts-mms-vits-benchmark`: storage-bound benchmark command.
- `scripts/acquire-mms-tamil.ps1`: downloads only the reviewed 145,242,872-byte
  SafeTensors file, verifies SHA-256, creates an isolated pinned runtime and emits a
  local attribution/license manifest.
- Automated gate: 188 tests pass; Ruff and strict mypy pass.

## Next execution sequence

1. MMS phonetic-Tanglish is rejected after owner review: 2/4 accepted, 3.0/5
   naturalness and 3.25/5 Jarvis fit. Keep it as evidence only.
2. Decide whether to authorize secure read-only Hugging Face authentication for
   metadata-only Indic Parler-TTS inspection, or remain anonymous and move to a
   consent-cleared custom voice/training path. Do not paste credentials into chat or
   store them in the project.
3. Benchmark the first passing challenger on development prompts using the frozen
   original voice profile. Keep held-out prompts sealed until normalization and style
   choices are fixed.
4. Choose a technical base. Original voice customization requires clean recordings
   from a consenting speaker or a license-cleared designed voice; no public-figure
   audio enters training or speaker conditioning.
