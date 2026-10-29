$projectRoot = Split-Path -Parent $PSScriptRoot
$storageRoot = Join-Path $projectRoot "storage"

$env:JARVIS_STORAGE_ROOT = $storageRoot
$env:JARVIS_MODEL_ROOT = Join-Path $storageRoot "models"
$env:JARVIS_ENGINE_ROOT = Join-Path $storageRoot "engines"
$env:JARVIS_DATASET_ROOT = Join-Path $storageRoot "datasets"
$env:JARVIS_BENCHMARK_ROOT = Join-Path $storageRoot "benchmarks"
$env:HF_HOME = Join-Path $storageRoot "cache\huggingface"
$env:TORCH_HOME = Join-Path $storageRoot "cache\torch"
$env:PIP_CACHE_DIR = Join-Path $storageRoot "cache\pip"
$env:UV_CACHE_DIR = Join-Path $storageRoot "cache\uv"
$env:TMP = Join-Path $storageRoot "temp"
$env:TEMP = Join-Path $storageRoot "temp"

$activationScript = Join-Path $projectRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path -LiteralPath $activationScript)) {
    throw "Jarvis virtual environment was not found at $activationScript"
}

& $activationScript
Write-Host "Jarvis environment active. Large-file storage: $storageRoot"

