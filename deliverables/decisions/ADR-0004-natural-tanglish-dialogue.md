# ADR-0004: Natural Tanglish and contextual dialogue

Status: Accepted  
Date: 10 October 2026

## Decision

Jarvis will treat the owner's natural spoken Tanglish as the primary interaction form. Pure English and pure Tamil remain control sets. The system will preserve the raw STT transcript, derive conservative Roman/Tamil-script variants, resolve dialogue context, and then interpret the request through three ordered layers:

1. deterministic commands, corrections, cancellation and safety-critical negation;
2. semantic intent and slot matching across spelling/code-switch variants;
3. a bounded local LLM fallback whose output must validate as a typed intent.

The executor never receives free-form LLM prose. Policy and approval evaluate only the validated intent and current trusted state.

Dialogue state will minimally track the active application, visible result set, selected object, previous action, last referenced entity and pending operation. This supports natural follow-ups such as “first one,” “adha,” “illa second one,” and “vendam cancel pannu.” Missing or ambiguous consequential scope triggers a narrow clarification.

## Evidence strategy

Three datasets have different roles and must not be merged conceptually:

- Owner speech corpus: how the owner actually sounds; used for acoustic STT evaluation.
- Tanglish text resources: spelling and code-switch variation; used for normalization and semantic evaluation after filtering and license review.
- Original dialogue scenarios: how Jarvis maintains context, clarifies, reports status and warns; used for dialogue evaluation.

Tamil-dubbed Iron Man and Avengers material is behavioral inspiration only. Copyrighted movie audio or exact dialogue is not a training corpus. Phase 1 scenarios are original and carry provenance metadata.

## Consequences

- Semantic intent, slots, entity preservation, negation and referent resolution are primary metrics; raw WER/CER are diagnostics.
- Held-out splitting occurs by entire dialogue scenario to prevent context leakage.
- The recorder saves the actual words spoken for elicited Tanglish prompts.
- JARVIS-style behavior means concise commands, calm precise responses, narrow clarification, status with reasons, and relevant proactive warnings—not unsafe autonomy or imitation of an actor/voice.
