param(
    [string[]]$Language = @("ta", "auto"),
    [ValidateSet("normalized", "raw")]
    [string]$AudioProfile = "normalized",
    [int]$Threads = 4,
    [int]$BeamSize = 5,
    [double]$TimeoutSeconds = 300,
    [switch]$WordEvidence,
    [string]$CandidateName = "openai-whisper-large-v3-turbo",
    [string]$RevisionShort = "41f01f3f",
    [string]$EngineLabel = "whisper-large-v3-turbo"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimePython = Join-Path $projectRoot "storage\engines\stt\faster-whisper-1.2.1-py312\Scripts\python.exe"
$worker = Join-Path $projectRoot "tools\faster_whisper_worker.py"
$model = Join-Path $projectRoot "storage\models\stt\ctranslate2\$CandidateName-$RevisionShort-int8"
$corpusName = if ($AudioProfile -eq "normalized") { "tanglish-v2-pilot-normalized.stt.jsonl" } else { "tanglish-v2-pilot.stt.jsonl" }
$corpus = Join-Path $projectRoot "storage\datasets\speech\evaluation\$corpusName"
$evaluation = Join-Path $projectRoot "storage\datasets\speech\evaluation\tanglish-v2-pilot.eval.jsonl"
$dialogues = Join-Path $projectRoot "storage\datasets\speech\dialogue-scenarios-v1.jsonl"
$corpusRoot = Join-Path $projectRoot "storage\datasets\speech"
$resultsRoot = Join-Path $projectRoot "storage\benchmarks\results"

foreach ($required in @($python,$runtimePython,$worker,$corpus,$evaluation,$dialogues)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required file is missing: $required" }
}
if (-not (Test-Path -LiteralPath (Join-Path $model "jarvis-conversion-manifest.json"))) {
    throw "Converted model manifest is missing for $CandidateName. Run its acquisition script first."
}
if ($Threads -lt 1 -or $Threads -gt 8) { throw "Threads must be between 1 and 8." }
if ($BeamSize -lt 1 -or $BeamSize -gt 10) { throw "BeamSize must be between 1 and 10." }

foreach ($mode in $Language) {
    if ($mode -notin @("ta", "auto")) { throw "Language must contain only ta or auto." }
    $evidenceSuffix = if ($WordEvidence) { "-words" } else { "" }
    $engineId = "$EngineLabel-int8-tanglish5-$AudioProfile-$mode-b$BeamSize$evidenceSuffix"
    $extraArguments = @()
    if ($WordEvidence) { $extraArguments = @("--word-timestamps") }
    & $python -m jarvis stt-faster-whisper-benchmark `
        --corpus $corpus `
        --corpus-root $corpusRoot `
        --python $runtimePython `
        --worker $worker `
        --model-dir $model `
        --engine-id $engineId `
        --threads $Threads `
        --timeout $TimeoutSeconds `
        --language $mode `
        --compute-type int8 `
        --beam-size $BeamSize `
        --corpus-language mixed `
        @extraArguments
    if ($LASTEXITCODE -ne 0) { throw "$CandidateName benchmark failed for language mode $mode." }

    $run = Get-ChildItem -LiteralPath $resultsRoot -Directory | Where-Object {
        $_.Name -like "$engineId-*"
    } | Sort-Object LastWriteTime | Select-Object -Last 1
    if ($null -eq $run -or -not (Test-Path -LiteralPath (Join-Path $run.FullName "samples.jsonl"))) {
        throw "Could not locate benchmark artifacts for $engineId."
    }
    $summary = Get-Content -Raw -LiteralPath (Join-Path $run.FullName "summary.json") | ConvertFrom-Json
    if ($summary.completed -ne $summary.samples -or $summary.failed -ne 0) {
        throw "Benchmark infrastructure failed for $engineId`: completed=$($summary.completed), failed=$($summary.failed). Semantic scoring was not run."
    }
    & $python -m jarvis dialogue-semantic-evaluate `
        --evaluation $evaluation `
        --dialogues $dialogues `
        --transcripts (Join-Path $run.FullName "samples.jsonl") `
        --output-dir (Join-Path $run.FullName "semantic")
    if ($LASTEXITCODE -ne 0) { throw "Semantic evaluation failed for language mode $mode." }
    Write-Host "Completed $mode candidate: $($run.FullName)"
}
