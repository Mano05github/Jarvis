param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot `
    "storage\engines\llm\llama-cpp-convert-py312\Scripts\python.exe"
$tokenizer = Join-Path $projectRoot `
    "storage\engines\llm\llama.cpp-src\build\bin\Release\llama-tokenize.exe"
$tokenizerDirectory = Join-Path $projectRoot `
    "storage\models\llm\huggingface\sugiv--Qwen3-8B-Tanglish-01582508"
$model = Join-Path $projectRoot `
    "storage\models\llm\gguf\sugiv--Qwen3-8B-Tanglish-01582508-Q4_K_M.gguf"
$cases = Join-Path $projectRoot "config\semantic-decoder\benchmark-v1.jsonl"
$output = Join-Path $projectRoot `
    "storage\benchmarks\results\qwen-tokenizer-parity.json"

foreach ($required in @($python, $tokenizer, $tokenizerDirectory, $model, $cases)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required tokenizer parity input is missing: $required"
    }
}

& $python (Join-Path $projectRoot "tools\verify_qwen_tokenizer_parity.py") `
    --tokenizer-dir $tokenizerDirectory `
    --model $model `
    --tokenizer-executable $tokenizer `
    --cases $cases `
    --output $output
if ($LASTEXITCODE -ne 0) {
    throw "Qwen Hugging Face/GGUF tokenizer parity failed. See $output"
}
Write-Host "Tokenizer parity report: $output"
