# Speech Engine Acquisition

## Prerequisites

- Git
- CMake
- Visual Studio 2022 Build Tools with the Desktop development with C++ workload
- Network access for the official GitHub and Hugging Face sources

## whisper.cpp

The acquisition script pins official repository commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`, builds `whisper-cli.exe` and `whisper-quantize.exe`, then records local SHA-256 values.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\acquire-whisper-cpp.ps1
```

The model preparation script downloads the official multilingual Base and Small GGML models into project storage, locally quantizes them to Q5_0, and creates manifests containing exact sizes and hashes.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-whisper-models.ps1
```

No generated binary or model is considered certified until its manifest is verified by the Jarvis model registry and it passes the target-hardware benchmark gates.

