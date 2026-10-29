$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$storageRoot = Join-Path $projectRoot "storage"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

$env:JARVIS_STORAGE_ROOT = $storageRoot
$env:JARVIS_ENGINE_ROOT = Join-Path $storageRoot "engines"
$env:HF_HOME = Join-Path $storageRoot "cache\huggingface"
$env:TORCH_HOME = Join-Path $storageRoot "cache\torch"
$env:PIP_CACHE_DIR = Join-Path $storageRoot "cache\pip"
$env:UV_CACHE_DIR = Join-Path $storageRoot "cache\uv"
$env:TMP = Join-Path $storageRoot "temp"
$env:TEMP = Join-Path $storageRoot "temp"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Create the Python 3.12.10 virtual environment at $python first."
}

$version = & $python --version
if ($version -ne "Python 3.12.10") {
    throw "Jarvis requires Python 3.12.10; found $version"
}

$uv = Get-Command uv -ErrorAction Stop
Push-Location $projectRoot
try {
    & $python tools\verify_workspace.py
    & $uv.Source sync --all-groups --python $python
    & $python -m jarvis doctor
    & $python -m pytest
} finally {
    Pop-Location
}

