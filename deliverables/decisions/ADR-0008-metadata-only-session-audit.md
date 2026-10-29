# ADR-0008: Persist metadata-only conversation audit chains

Status: Accepted  
Date: 12 October 2026

## Context

The text-first controller needs durable evidence of session lifecycle, interaction
modes, clarification state, rejected plans and simulated policy outcomes. Persisting
prompts, replies, provider errors or configuration would create an unnecessary
collection of personal content and could expose credentials or raw secrets.

## Decision

Each interactive text session writes one local JSONL file under
`storage/audit/sessions`. The writer exposes only typed, allowlisted metadata methods;
it has no input for prompt bodies, model reply bodies, system instructions, provider
configuration, credential references or exception text.

Events carry the session UUID, optional task UUID, fixed event type, bounded canonical
summary fields and data-class labels. Registered simulated actions may record only
their canonical action/resource identifiers and generated intent/policy UUIDs. Every
event includes the preceding digest and a SHA-256 digest over its canonical content.
The file is flushed and synchronized after each append, and an existing chain is
validated before reuse.

The audit directory is project-local and ignored by Git. Session metadata is marked
`PERSONAL`; conversation content retention remains disabled.

## Consequences

- Normal sessions are auditable without retaining what the owner or model said.
- Modification, deletion within the chain and reordering are detected when the file
  is validated.
- A hash chain is tamper-evident, not authenticated: an attacker able to replace the
  whole file can recompute it, delete it or roll it back. Signing, protected anchors,
  rotation and retention enforcement remain future control-plane work.
- Audit persistence failures stop the associated trusted state transition rather
  than silently continuing without its record.
