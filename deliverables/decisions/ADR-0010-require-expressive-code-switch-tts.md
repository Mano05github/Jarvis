# ADR-0010: Require expressive code-switching for the primary TTS voice

Status: Accepted  
Date: 15 October 2026

## Context

The first real MMS Tamil development run was technically stable, but owner listening
found that Jarvis spoke in pure Tamil rather than natural Tanglish and did not have
the desired friendly companion tone. This is an architectural limitation, not a
small pronunciation defect: the MMS checkpoint is a single-language, single-speaker
Tamil model without conversational style conditioning.

The desired interaction quality is calm, capable, warm, concise and occasionally
lightly witty, similar to the broad assistant qualities associated with cinematic
AI companions. Jarvis must remain an original voice and must not reproduce a
fictional character performance, its actor's voice or another identifiable person.

## Decision

MMS Tamil is rejected as the primary Jarvis voice. It may remain an attributed,
non-commercial Tamil-only fallback while its CC-BY-NC-4.0 terms apply.

The primary TTS candidate must:

- preserve Tamil, English and natural code-switching without translating everything
  into formal Tamil;
- speak Tamil script, Romanized Tamil and English technical terms in one consistent
  original voice;
- expose usable prosody, style-prompt or expressive conditioning for a warm,
  friendly and confidently restrained delivery;
- run locally after approved acquisition and pass the existing latency, memory,
  cancellation, licensing and identity-distinctness gates.

AI4Bharat IndicF5 and the older AI4Bharat Indic-TTS path enter source/runtime review.
Language coverage alone is insufficient: each must show direct evidence or measured
behavior for code-switching and expressive control before weights are acquired.

The canonical target traits are stored in
`config/tts/jarvis-voice-v1.toml`. These are high-level delivery qualities, not a
request to copy Iron Man's JARVIS voice or dialogue.

## Consequences

- No further MMS tuning or held-out testing is justified for primary-voice selection.
- The MMS benchmark remains useful as a Tamil speed/memory baseline and fallback.
- The next work item is metadata-only inspection of expressive multilingual
  candidates, followed by a small development-only Tanglish gate.
- Voice customization still requires consent-cleared speech or weights whose license
  permits the intended use.
