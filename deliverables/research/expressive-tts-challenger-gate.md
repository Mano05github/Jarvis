# Expressive Tanglish TTS challenger gate

Updated: 15 October 2026

## Required behavior

The primary Jarvis voice must sound like one friendly bilingual speaker, not a Tamil
announcer alternating with an English voice. It must preserve the wording produced by
the companion model, including English application names and technical terms.

Target delivery is warm, calm, precise, conversational and lightly witty where the
context allows. Cinematic-assistant references supply only these abstract interaction
traits. Exact actor, public-figure and fictional-character voice replication is out of
scope.

## Candidate order

1. AI4Bharat Indic Parler-TTS code/model review, with Parler-TTS code pinned at
   `d108732cd57788ec86bc857d99a6cabd66663d68`.
2. Consider another offline expressive multilingual engine only if Indic Parler-TTS
   fails code-switch, licensing or target-laptop runtime gates.

IndicF5 is rejected because its model access is credential-gated while licensing and
English/Tanglish evidence remain unresolved. Indic-TTS is rejected as monolingual and
fixed-style.

## Pre-acquisition gates

- Distinguish code license, model-weight license and training/reference-data rights.
- Record immutable source and model revisions plus weight hashes and sizes.
- Reject required remote inference, unreviewed remote code or a cloud-only path.
- Confirm Windows/Python 3.12 CPU installation or define an isolated compatible
  worker without changing the project environment.
- Find explicit evidence for Tamil, English and mixed-language synthesis.
- Find explicit style/prosody conditioning; a fixed formal voice does not satisfy the
  user requirement.
- Reject any workflow that requires unconsented celebrity or copyrighted film audio.

## Development gate

Use only development prompts first. A candidate advances when the owner scores Tamil
clarity at least 4/5, mixed clarity at least 3.5/5, friendliness at least 4/5 and
identity distinctness as passing. It must also remain below 2 GB peak RSS and target
RTF <= 1.0. Held-out prompts remain sealed until the text normalization and style
profile are frozen.
