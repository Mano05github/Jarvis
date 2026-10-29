# ADR-0009: Use an original, consent-cleared Jarvis voice

Status: Accepted  
Date: 13 October 2026

## Context

The owner wants a powerful Tamil cinematic voice for Jarvis and supplied a short
film-dialogue clip containing an identifiable public figure's voice and background
music. Source separation can reduce music, but it cannot establish speaker consent,
training rights or clean studio-quality speech, and it may introduce artifacts.

## Decision

Jarvis will use an original Tamil-capable voice defined by non-identifying qualities:
warm low register, confident energy, crisp consonants, concise delivery and natural
Tanglish pronunciation. It must not reproduce, clone or intentionally imitate
Vijay's identifiable voice or any other real person's identity.

The supplied movie clip is reference-only for broad pacing and energy. It will not be
ingested into a training, adaptation, speaker-embedding or production voice dataset,
whether or not background music is separated.

Any custom voice data must come from a speaker who has explicitly consented to this
use, with documented provenance and rights, or from a model/voice whose license
expressly permits the intended local use. Recordings must be clean, dry speech rather
than copyrighted film audio. TTS remains local and offline after approved acquisition.

## Consequences

- Voice specification can begin immediately, and local TTS prototyping can begin
  after the simulated approval-state gate.
- Production integration occurs only after a TTS profile passes clarity, latency,
  memory, cancellation, provenance and identity-distinctness checks.
- Music/source separation may be used for private listening comparison or acoustic
  reference, but it does not convert the supplied clip into training data.
- A consent-cleared voice actor, a properly licensed original voice or a deliberately
  designed synthetic voice is required for customization.
