# Expressive TTS candidate review v1

Date: 15 October 2026

## Decision

AI4Bharat Indic-TTS is rejected as the primary Jarvis voice before weight download.
Its documented models are monolingual FastPitch/HiFi-GAN voices, it provides no
English/Tanglish or expressive-style evidence, and its setup targets a legacy
Linux/CUDA training stack. Its MIT code license does not establish the separate model
weight or dataset terms needed for deployment.

AI4Bharat IndicF5 is rejected. Anonymous model-repository access requires credentials,
while English/Tanglish support and licensing were already unresolved. Jarvis will not
introduce a Hugging Face token for this weak candidate.

## IndicF5 evidence

- Tamil is one of eleven documented Indian languages.
- It supports local inference and contains an explicit CPU code path.
- Reference audio controls speaker characteristics and prosody, which could support
  the friendly original voice profile when the reference speech is consent-cleared.
- A bundled Tamil happy-style prompt exists, but its redistribution and speaker
  consent/provenance have not yet been established.

### Blocking findings

- English and Tanglish/code-switch synthesis are not documented.
- The GitHub source contains no license file or declared code license.
- The model is loaded with `trust_remote_code=True`; the exact Hugging Face model
  revision and custom code must be pinned and reviewed locally.
- Inference requires reference audio plus an exact transcript. Using an arbitrary
  actor, public-figure or film clip is prohibited; a bundled prompt also cannot be
  assumed safe until its source rights are known.
- The documented environment is Python 3.10. Dependencies include a conflicting
  `numpy<=1.26.4`, `transformers<4.50`, Torch/Torchaudio, Vocos and packages that are
  unnecessary or problematic for a CPU-only Windows runtime. An isolated environment
  and dependency minimization are mandatory.
- CPU code availability does not establish acceptable performance on the Ryzen 5
  7520U; F5 diffusion/flow inference may miss the RTF and memory gates.

## Next gate

The next candidate is AI4Bharat Indic Parler-TTS. Its description-conditioned
architecture is a better match for Jarvis's original friendly delivery profile, but
Tamil/English code switching, model licensing, weight size and CPU feasibility remain
unproven.

The model repository also requires credentials when accessed anonymously. Indic
Parler-TTS is therefore rejected under the no-token metadata gate; no weights were
downloaded.

Run `scripts\inspect-indic-parler-source.ps1` in the owner's network context. It pins
and inspects the Parler-TTS code plus the exact Indic Parler model repository without
downloading LFS weights. It records licenses, dependencies, LFS sizes/hashes, custom
Python files, language/style evidence and the remote-code boundary.

No weights were downloaded. IndicF5, Indic-TTS and Indic Parler-TTS are rejected.
The measured MMS phonetic-Tanglish path continues only as an interim local fallback
while a clearly public, licensed, expressive Tamil-English engine is sought.
