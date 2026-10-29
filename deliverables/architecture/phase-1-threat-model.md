# Phase 1 Threat Model

## Assets

- Microphone audio, transcripts and personal pronunciation samples
- Model weights and executable inference engines
- Configuration, contracts, benchmark results and integrity metadata
- Future approval, capability and audit keys

## Trust boundaries

1. Microphone device to interaction process
2. Downloaded model/source to local model registry
3. Interaction service to orchestration contracts
4. Project configuration to running process
5. Telemetry/reporting to persisted storage

## Primary threats and controls

| Threat | Phase 1 control |
|---|---|
| Normal conversation is retained | In-memory bounded buffers; persistence only in explicit benchmark mode |
| Private samples leave the device | Offline speech engines; no upload adapter or remote STT/TTS dependency |
| Malicious/tampered model | Source/license record, expected size, SHA-256, downloaded/verified/certified states |
| Path traversal or junction escape | Canonical path resolution under an allowlisted project-local root |
| Dependency or build drift | Python 3.12.10 pin, `pyproject.toml`, generated lock and CI checks |
| Sensitive text enters telemetry | Allowlisted numeric/timing fields; no audio/transcript bodies in operational events |
| CPU/RAM exhaustion | Preflight admission, bounded buffers, serialized heavy inference and cancellation |
| Contract ambiguity grants authority | Extra fields forbidden; authority fields are distinct typed contracts |
| Benchmark data is accidentally committed | `storage` ignored; only synthetic fixtures allowed in `tests/fixtures` |

## Phase 1 exclusions

Desktop control, MCP tools, remote reasoning and persistent personal memory are not enabled, so they cannot expand Phase 1 authority.

