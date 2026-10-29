# ADR-0007: Use one primary multilingual LLM for companionship and planning

**Status:** Accepted  
**Date:** 12 October 2026

## Context

The owner will speak arbitrary natural Tanglish, English and Tamil—not a finite command vocabulary. Jarvis must also support casual conversation, questions, corrections, contextual references and mixed conversation/action turns. A deterministic Tanglish decoder cannot provide that open-domain behavior. The rejected Qwen3-8B-Tanglish Q4 experiment also showed that a second resident 8B semantic model is unsuitable for the target laptop.

## Decision

Use one configurable primary multilingual LLM behind a provider-neutral gateway for both conversation and plan proposal. The model returns a typed `InteractionEnvelope`: `chat`, `answer`, `clarify`, `plan`, `mixed`, `confirm`, `cancel` or `no_action`.

The model has no tool or authorization authority. A plan is only a proposal. Trusted code validates request identity, schema, references, assumptions and dependency graphs before deterministic risk, policy, approval, capability issuance, execution and verification. Missing consequential information must produce a narrow clarification rather than a guessed target.

Provider credentials are references to Windows user-bound DPAPI blobs. TOML configuration contains no secret value. Remote routing is denied for local-only requests and for `SECRET` or `PROHIBITED` data.

## Consequences

- Natural Tanglish vocabulary is not restricted to reviewed phrases.
- Casual companionship and action planning share dialogue context and personality.
- Azure OpenAI, OpenAI, Anthropic and local OpenAI-compatible/Ollama/llama.cpp profiles can be swapped by configuration.
- The deterministic Tanglish decoder remains an optional fast-path helper, safety-marker detector and regression baseline; it is not the general understanding layer.
- ADR-0006 remains valid for its benchmark evidence and optional bounded helper. Its choice of the deterministic compiler as the default general semantic route is superseded.
- Qwen3-8B Q4 remains rejected and is not a runtime dependency.

## Acceptance gates

1. Every provider passes the same contract and malformed-output suite.
2. Casual, clarification, planning and mixed-turn Tanglish evaluations pass on held-out cases.
3. No conversational response can implicitly trigger a tool.
4. Missing consequential fields always pause for clarification.
5. Privacy-incompatible fallback is impossible.
6. Tool execution remains impossible without deterministic policy and a scoped capability.
