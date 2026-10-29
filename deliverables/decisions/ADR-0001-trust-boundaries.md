# ADR-0001: Separate observation, reasoning, authority, execution and verification

Status: Accepted  
Date: 10 October 2026

## Decision

Jarvis is implemented as separate trust domains. Models and LangGraph may propose structured intentions but cannot authorize or verify their own effects. A deterministic policy gateway and technically separate trusted UI issue narrow capability grants. Executors consume grants, and an independent verifier determines outcomes.

## Consequences

- No model, character, webpage or MCP server can approve an action.
- Every consequential effect requires a typed intent, policy decision, scoped grant and audit record.
- A tool returning `success` is insufficient; postconditions require independent evidence.
- More processes and contracts are required, but failures and compromise remain contained.

