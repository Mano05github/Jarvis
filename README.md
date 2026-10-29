# Jarvis

[![CI](https://github.com/Mano05github/Jarvis/actions/workflows/ci.yml/badge.svg)](https://github.com/Mano05github/Jarvis/actions/workflows/ci.yml)

Jarvis is a Windows-first, local-privacy-first personal assistant built around a strict rule: an AI model may propose an action, but it never becomes the authority that executes it.

The project separates observation, language understanding, planning, authorization, execution, and verification into explicit trust boundaries. Its current Phase 1 runtime focuses on typed contracts, Tamil/English/Tanglish interaction research, governed speech pipelines, privacy-aware LLM routing, and a constrained Windows capability broker.

> [!IMPORTANT]
> Jarvis is under active development. Desktop actions are currently simulation-only, and the Windows broker fails closed. Do not treat this repository as a production automation agent.

## Highlights

- **Local-first privacy**: models, recordings, datasets, caches, logs, and credentials stay in project-local ignored storage.
- **Typed action pipeline**: model output is treated as untrusted input and compiled into validated intents and plans.
- **Explicit authorization**: consequential actions require scoped, expiring, digest-bound capability grants.
- **Fail-closed Windows broker**: the .NET broker uses current-user named pipes, caller identity checks, bounded messages, and DPAPI/HMAC-backed grants.
- **Tamil and Tanglish research**: reproducible STT, TTS, dialogue, and semantic evaluation workflows are included.
- **Governed resource use**: memory admission, process supervision, timeouts, cancellation, and Job Object containment protect the host.
- **Privacy-safe audit trail**: session metadata is hash-chained without persisting prompt or reply bodies.
- **Provider-neutral LLM gateway**: local and remote providers are routed through privacy policy; prohibited data cannot fall back to a remote service.

## Trust model

```text
User input
    |
    v
Speech / text evidence  (untrusted)
    |
    v
Companion + planner     (authority: none)
    |
    v
Typed compiler -> policy -> approval
    |
    v
Capability grant
    |
    v
Constrained Windows broker -> evidence -> audit
```

The language model cannot call a shell or directly control Windows. Plans must pass deterministic validation and policy checks before the broker can consider them. Cancellation, corrections, expiry, replay prevention, and approval binding are enforced outside the model.

## Requirements

- Windows 10 or Windows 11
- Python **3.12.10**
- [uv](https://docs.astral.sh/uv/)
- PowerShell 5.1 or newer
- .NET 8 SDK and CMake only when building the native broker or speech runtime

Large speech models and external engines are optional and are not stored in Git.

## Quick start

```powershell
git clone https://github.com/Mano05github/Jarvis.git
cd Jarvis

uv venv --python 3.12.10
uv sync --all-groups

uv run jarvis storage-init
uv run jarvis doctor
uv run pytest
```

To activate the prepared project environment and redirect model/cache/temp paths into `storage`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\enter-jarvis.ps1
```

Once the virtual environment exists, the full workspace check can also be run with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

## Useful commands

```powershell
# List all developer and evaluation commands
uv run jarvis --help

# Export versioned contract schemas
uv run jarvis schemas-export

# Validate a provider configuration without exposing credentials
uv run jarvis llm-config-validate --config .\config\llm-providers.local.toml

# Run formatting, lint, typing, and tests
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov

# Run native component checks when their toolchains are installed
.\scripts\test-windows-broker.ps1
.\scripts\test-native-speech-runtime.ps1
```

Speech acquisition and benchmarking scripts live under [`scripts`](scripts). They pin upstream sources, verify downloaded artifacts, apply bounded execution limits, and write generated results beneath ignored local storage.

## Project layout

| Path | Purpose |
| --- | --- |
| [`src/jarvis`](src/jarvis) | Python control core, contracts, runtime, LLM gateway, storage, and evaluation tooling |
| [`native`](native) | Constrained .NET Windows broker and dependency-free native speech runtime |
| [`config`](config) | Versioned policies, application registry, runtime limits, evaluation fixtures, and provider examples |
| [`tests`](tests) | Unit and contract test suites |
| [`scripts`](scripts) | Reproducible setup, acquisition, inspection, benchmark, and verification workflows |
| [`benchmarks`](benchmarks) | Versioned benchmark manifests, prompts, and recording guidance |
| [`storage`](storage) | Ignored machine-local models, recordings, datasets, secrets, caches, and results |

## Configuration and secrets

The base runtime configuration is in [`config/base/jarvis.toml`](config/base/jarvis.toml), while the reviewed desktop application allowlist is in [`config/applications.toml`](config/applications.toml). Registering an application makes it discoverable to the compiler; it does not grant execution authority.

Copy [`.env.example`](.env.example) only if you need explicit path overrides. Never commit `.env`, local provider configuration, credentials, recordings, model weights, or the contents of `storage`. Provider credentials are stored as Windows user-bound DPAPI blobs and are referenced from secret-free configuration.

## Current status

The trusted Python control core, typed contracts, simulation-only text sessions, provider gateway, metadata-only audit log, Windows broker boundary, native speech contracts, and speech evaluation harnesses are implemented. Real desktop execution remains deliberately disabled while authorization and native-runtime certification continue.

## Development principles

1. Models propose; deterministic code decides.
2. Every consequential action is typed, scoped, reviewable, and revocable.
3. Privacy policy is enforced before provider routing.
4. Missing evidence, expired approval, ambiguous intent, or resource pressure causes a safe refusal.
5. Benchmarks and architectural claims must be reproducible from versioned configuration, fixtures, and source.
