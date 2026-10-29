# ADR-0002: Speech processing is local and offline

Status: Accepted  
Date: 10 October 2026

## Decision

STT and TTS run locally after explicitly approved model downloads. The baseline must support Tamil, English and code switching on the Ryzen 5 7520U CPU. Push-to-talk precedes wake-word activation.

## Consequences

- Whisper.cpp Base/Small Multilingual Q5 are the mandatory STT candidates.
- Tamil MMS VITS and AI4Bharat Indic-TTS are evaluated; eSpeak NG is the emergency fallback.
- Raw audio is not retained outside explicit benchmark mode.
- Heavy inference is serialized and audio always receives scheduler priority.

