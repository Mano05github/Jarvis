param(
    [string[]]$Language = @("ta", "auto"),
    [int]$Threads = 4,
    [double]$TimeoutSeconds = 120,
    [switch]$Normalized,
    [switch]$ContextBias
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$revisionShort = "ac0d71cd"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimePython = Join-Path $projectRoot "storage\engines\stt\faster-whisper-1.2.1-py312\Scripts\python.exe"
$worker = Join-Path $projectRoot "tools\faster_whisper_worker.py"
$model = Join-Path $projectRoot "storage\models\stt\ctranslate2\vasista22-whisper-tamil-small-$revisionShort-int8"
$corpusName = if ($Normalized) { "tanglish-v2-pilot-normalized.stt.jsonl" } else { "tanglish-v2-pilot.stt.jsonl" }
$caseName = if ($Normalized) { "tanglish5-normalized" } else { "tanglish5" }
if ($ContextBias) { $caseName = "$caseName-context" }
$corpus = Join-Path $projectRoot "storage\datasets\speech\evaluation\$corpusName"
$evaluation = Join-Path $projectRoot "storage\datasets\speech\evaluation\tanglish-v2-pilot.eval.jsonl"
$dialogues = Join-Path $projectRoot "storage\datasets\speech\dialogue-scenarios-v1.jsonl"
$corpusRoot = Join-Path $projectRoot "storage\datasets\speech"
$resultsRoot = Join-Path $projectRoot "storage\benchmarks\results"

foreach ($required in @($python,$runtimePython,$worker,$corpus,$evaluation,$dialogues)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required file is missing: $required"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $model "jarvis-conversion-manifest.json"))) {
    throw "Converted model manifest is missing. Run scripts\acquire-tamil-whisper.ps1 first."
}
if ($Threads -lt 1 -or $Threads -gt 8) {
    throw "Threads must be between 1 and 8."
}
foreach ($mode in $Language) {
    if ($mode -notin @("ta","auto")) {
        throw "Language must contain only ta or auto."
    }
    $engineId = "vasista22-tamil-small-int8-$caseName-$mode"
    $extraArguments = @()
    if ($ContextBias) {
        $hotwords = "Jarvis Notepad Visual Studio Code VS Code open close download downloads latest vendam aama munnadi pannu"
        $extraArguments = @("--hotwords", $hotwords)
    }
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
        --corpus-language mixed `
        @extraArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Tamil Whisper benchmark failed for language mode $mode."
    }
    $run = Get-ChildItem -LiteralPath $resultsRoot -Directory | Where-Object {
        $_.Name -like "$engineId-*"
    } | Sort-Object LastWriteTime | Select-Object -Last 1
    if ($null -eq $run -or -not (Test-Path -LiteralPath (Join-Path $run.FullName "samples.jsonl"))) {
        throw "Could not locate benchmark artifacts for $engineId."
    }
    $summaryPath = Join-Path $run.FullName "summary.json"
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        throw "Benchmark summary is missing for $engineId."
    }
    $summary = Get-Content -Raw -LiteralPath $summaryPath | ConvertFrom-Json
    if ($summary.completed -ne $summary.samples -or $summary.failed -ne 0) {
        throw "Benchmark infrastructure failed for $engineId`: completed=$($summary.completed), failed=$($summary.failed). Semantic scoring was not run."
    }
    & $python -m jarvis dialogue-semantic-evaluate `
        --evaluation $evaluation `
        --dialogues $dialogues `
        --transcripts (Join-Path $run.FullName "samples.jsonl") `
        --output-dir (Join-Path $run.FullName "semantic")
    if ($LASTEXITCODE -ne 0) {
        throw "Semantic evaluation failed for language mode $mode."
    }
    Write-Host "Completed $mode candidate: $($run.FullName)"
}
