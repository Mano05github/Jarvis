param(
    [int]$Threads = 4,
    [int]$Seed = 7,
    [double]$StartupTimeoutSeconds = 300,
    [double]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePython = Join-Path $projectRoot "storage\engines\tts\mms-vits-transformers-4.57.6-py312\Scripts\python.exe"
$model = Join-Path $projectRoot "storage\models\tts\huggingface\facebook-mms-tts-tam-e9cf59da"
$manifest = Join-Path $projectRoot "storage\datasets\speech\tts-eval-v1.jsonl"
$modelManifest = Join-Path $projectRoot "storage\models\tts\manifests\facebook-mms-tts-tam-e9cf59da.json"
$lexicon = Join-Path $projectRoot "config\tts\mms-tanglish-pronunciation-v1.toml"
$worker = Join-Path $projectRoot "tools\mms_vits_worker.py"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

foreach ($required in @($runtimePython, $model, $manifest, $modelManifest, $lexicon, $worker, $projectPython)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required benchmark input is missing: $required" }
}

& $projectPython -m jarvis model-verify $modelManifest
if ($LASTEXITCODE -ne 0) { throw "MMS Tamil model integrity verification failed." }

& $projectPython -m jarvis tts-mms-vits-benchmark `
    --manifest $manifest `
    --python $runtimePython `
    --worker $worker `
    --model-dir $model `
    --engine-id "mms-tanglish-stopgap-e9cf59da" `
    --threads $Threads `
    --seed $Seed `
    --speaking-rate 0.92 `
    --noise-scale 0.60 `
    --noise-scale-duration 0.75 `
    --pronunciation-lexicon $lexicon `
    --startup-timeout $StartupTimeoutSeconds `
    --timeout $TimeoutSeconds `
    --language mixed `
    --split development
if ($LASTEXITCODE -ne 0) { throw "MMS Tanglish stopgap benchmark failed." }
