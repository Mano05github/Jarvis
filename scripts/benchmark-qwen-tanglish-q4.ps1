param(
    [ValidateSet("packet", "core")]
    [string]$Mode = "packet",
    [ValidateSet("oracle", "all")]
    [string]$Suite = "oracle",
    [int]$StabilityRequests = 0,
    [int]$Threads = 4,
    [int]$ContextSize = 1024,
    [int]$BatchSize = 128,
    [int]$MicroBatchSize = 64,
    [int]$MaxOutputTokens = 48
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$modelManifest = Join-Path $projectRoot `
    "storage\models\llm\manifests\sugiv--Qwen3-8B-Tanglish-01582508-Q4_K_M.json"
$llamaManifest = Join-Path $projectRoot "storage\engines\llm\manifests\llama.cpp-build.json"
if (-not (Test-Path -LiteralPath $modelManifest -PathType Leaf)) {
    throw "Qwen Q4_K_M manifest is missing. Run scripts\acquire-qwen-tanglish-q4.ps1 first."
}
if (-not (Test-Path -LiteralPath $llamaManifest -PathType Leaf)) {
    throw "llama.cpp build manifest is missing."
}
$modelInfo = Get-Content -Raw -LiteralPath $modelManifest | ConvertFrom-Json
$llamaInfo = Get-Content -Raw -LiteralPath $llamaManifest | ConvertFrom-Json
$model = Join-Path $projectRoot "storage\models\llm\$([string]$modelInfo.relative_file)"
$server = Join-Path $projectRoot ([string]$llamaInfo.server_executable).Replace('/', '\')
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $model).Hash.ToLowerInvariant() -ne $modelInfo.sha256) {
    throw "Qwen GGUF hash verification failed."
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $server).Hash.ToLowerInvariant() -ne $llamaInfo.server_sha256) {
    throw "llama-server hash verification failed."
}
$rubricName = if ($Mode -eq "core") { "rubric-core-v1.txt" } else { "rubric-v1.txt" }
$grammarName = if ($Mode -eq "core") { "semantic-core-v1.gbnf" } else { "semantic-packet-v1.gbnf" }

& $python -m jarvis qwen-semantic-benchmark `
    --executable $server `
    --model $model `
    --cases (Join-Path $projectRoot "config\semantic-decoder\benchmark-v1.jsonl") `
    --rubric (Join-Path $projectRoot "config\semantic-decoder\$rubricName") `
    --codebooks (Join-Path $projectRoot "config\semantic-decoder\codebooks-v1.json") `
    --grammar (Join-Path $projectRoot "config\semantic-decoder\$grammarName") `
    --engine-id "qwen3-8b-tanglish-q4-k-m-$Mode" `
    --mode $Mode `
    --threads $Threads `
    --context-size $ContextSize `
    --batch-size $BatchSize `
    --micro-batch-size $MicroBatchSize `
    --max-output-tokens $MaxOutputTokens `
    --suite $Suite `
    --stability-requests $StabilityRequests
if ($LASTEXITCODE -ne 0) { throw "Qwen semantic benchmark failed." }
