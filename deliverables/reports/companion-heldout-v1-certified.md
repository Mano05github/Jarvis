# Companion/planner held-out v1 certification

Date: 13 October 2026  
Provider profile: Azure OpenAI `gpt-5.6-sol` deployment  
Evidence: `storage/benchmarks/results/llm-companion-20261013T143522Z`

## Result

- 40 of 40 cases passed; certified accuracy and mode accuracy were 100%.
- All ten categories passed 4/4: companionship, knowledge, correction, anaphora,
  clarification, cancellation, planning, multi-step planning, ambiguity and prompt
  injection.
- Provider failures: zero.
- Median latency: 3.93 seconds; maximum latency: 5.83 seconds.
- Authority isolation, exact registered plan/argument checks, script matching,
  brevity, clarification fields, known-answer terms and no-plan gates all passed.

## Remediation history

The initial run and adjudication are retained in
`deliverables/reports/companion-heldout-v1-initial.md`. Plan-bearing `mixed` envelopes
were recognized correctly, ambiguous alternative targets were required to clarify,
and contextual Tanglish correction such as `Notepad illa, VS Code` was distinguished
from an unresolved alternative. A targeted correction retest passed before the full
certification run.

## Scope

This certification covers the current synthetic text companion/planner pack and
configured provider. It does not grant tool authority, certify desktop execution or
replace speech/STT/TTS certification. The runtime remains simulation-only.
