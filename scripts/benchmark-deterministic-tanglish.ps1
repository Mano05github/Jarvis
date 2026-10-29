param(
    [ValidateRange(1, 10000)]
    [int]$Repetitions = 100
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

& $python -m jarvis deterministic-semantic-benchmark `
    --cases (Join-Path $projectRoot "config\semantic-decoder\benchmark-v1.jsonl") `
    --codebooks (Join-Path $projectRoot "config\semantic-decoder\codebooks-v1.json") `
    --engine-id "deterministic-tanglish-v1" `
    --repetitions $Repetitions
if ($LASTEXITCODE -ne 0) { throw "Deterministic Tanglish benchmark failed." }
