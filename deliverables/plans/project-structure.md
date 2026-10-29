# Jarvis Project Structure

```text
Jarvis/
├─ apps/                         # Avatar and trusted user interfaces
├─ services/                     # Independently supervised runtime services
├─ native/                       # C# Windows brokers
├─ src/jarvis/                   # Shared Python packages
├─ benchmarks/speech/            # STT/TTS benchmark harness code
├─ config/{base,schemas,examples}
├─ policies/{immutable,privacy,tests}
├─ tests/{unit,contract,integration,security,fixtures}
├─ artifacts/                    # Small reproducible generated artifacts
├─ assets/character-references/  # Source visual references
├─ deliverables/
│  ├─ architecture/
│  ├─ plans/
│  ├─ decisions/
│  ├─ research/
│  ├─ reports/
│  ├─ checkpoints/
│  └─ manifests/
├─ tools/                        # Generators and developer utilities
├─ scripts/                      # Bootstrap and verification scripts
├─ storage/                      # Models, engines, datasets and other large/private files
└─ .venv/                        # Python 3.12.10 environment
```

`deliverables` replaces a separate `docs` directory. Benchmark code is versioned under `benchmarks`; private recordings and large results remain under `storage`.

