$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "benchmarks\speech\tts-eval-v1.jsonl"
$destination = Join-Path $projectRoot "storage\datasets\speech\tts-eval-v1.jsonl"

if (-not (Test-Path -LiteralPath $source)) {
    throw "Tracked TTS evaluation manifest is missing: $source"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
if (Test-Path -LiteralPath $destination) {
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if ($sourceHash -ne $destinationHash) {
        throw "Existing storage manifest differs; preserve or remove it explicitly: $destination"
    }
} else {
    Copy-Item -LiteralPath $source -Destination $destination
}

& (Join-Path $projectRoot ".venv\Scripts\python.exe") -c `
    "from pathlib import Path; from jarvis.benchmarking.tts import load_tts_manifest; p=Path(r'$destination'); print(f'Validated {len(load_tts_manifest(p))} TTS prompts:', p)"
if ($LASTEXITCODE -ne 0) { throw "TTS manifest validation failed." }
