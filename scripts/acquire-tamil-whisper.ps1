param(
    [string]$Revision = "ac0d71cd70d4c66aec7126996cd9e56e97e698b7",
    [switch]$SkipDependencyInstall,
    [switch]$SkipConversion
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceProbe = Join-Path $projectRoot "storage\models\stt\candidate-probes\vasista22-whisper-tamil-small-source"
$sourceSummary = Join-Path $projectRoot "storage\models\stt\candidate-probes\vasista22-whisper-tamil-small-source.json"
$modelRoot = Join-Path $projectRoot "storage\models\stt\huggingface\vasista22-whisper-tamil-small-$($Revision.Substring(0, 8))"
$convertedRoot = Join-Path $projectRoot "storage\models\stt\ctranslate2\vasista22-whisper-tamil-small-$($Revision.Substring(0, 8))-int8"
$runtimeRoot = Join-Path $projectRoot "storage\engines\stt\faster-whisper-1.2.1-py312"
$runtimePython = Join-Path $runtimeRoot "Scripts\python.exe"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$uvCache = Join-Path $projectRoot "storage\cache\uv"
$tempRoot = Join-Path $projectRoot "storage\temp"
$weightName = "pytorch_model.bin"
[Int64]$expectedBytes = 967099139
$expectedSha256 = "8bad6eccfd11ec5b41a9116e41845d8ecd92fe1c1236cc916a082d0a2ce402d0"
$weight = Join-Path $modelRoot $weightName
$partial = "$weight.partial"
$downloadUrl = "https://huggingface.co/vasista22/whisper-tamil-small/resolve/$Revision/pytorch_model.bin?download=true"

if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Project Python is missing: $projectPython"
}
if (-not (Test-Path -LiteralPath $sourceSummary)) {
    throw "Run scripts\inspect-tamil-whisper-source.ps1 before acquisition."
}
$inspected = Get-Content -Raw -LiteralPath $sourceSummary | ConvertFrom-Json
if ($inspected.revision -ne $Revision) {
    throw "Pinned revision mismatch: expected $Revision, found $($inspected.revision)"
}
if ($inspected.license -ne "apache-2.0") {
    throw "Unexpected model license: $($inspected.license)"
}

$disk = [System.IO.DriveInfo]::new((Split-Path -Qualifier $projectRoot))
if ($disk.AvailableFreeSpace -lt 6GB) {
    throw "At least 6 GB free space is required for weights, conversion and dependencies."
}

New-Item -ItemType Directory -Force -Path $modelRoot,$uvCache,$tempRoot | Out-Null
$ordinaryFiles = @(
    "added_tokens.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "normalizer.json",
    "preprocessor_config.json",
    "README.md",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json"
)
foreach ($name in $ordinaryFiles) {
    $source = Join-Path $sourceProbe $name
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Pinned source file is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $modelRoot $name) -Force
}

$validWeight = $false
if (Test-Path -LiteralPath $weight) {
    $item = Get-Item -LiteralPath $weight
    if ($item.Length -eq $expectedBytes) {
        $actualHash = (Get-FileHash -LiteralPath $weight -Algorithm SHA256).Hash.ToLowerInvariant()
        $validWeight = $actualHash -eq $expectedSha256
    }
    if (-not $validWeight) {
        throw "Existing weight file failed the pinned size/hash check: $weight"
    }
}

if (-not $validWeight) {
    Write-Host "Downloading pinned PyTorch weights (967,099,139 bytes)..."
    & curl.exe --location --fail --retry 5 --retry-delay 3 --continue-at - `
        --user-agent "Jarvis-Phase1-Model-Acquisition/1.0" `
        --output $partial $downloadUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Model download failed with curl exit code $LASTEXITCODE"
    }
    $downloaded = Get-Item -LiteralPath $partial
    if ($downloaded.Length -ne $expectedBytes) {
        throw "Downloaded size mismatch: expected $expectedBytes, got $($downloaded.Length)"
    }
    $actualHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedSha256) {
        throw "Downloaded SHA-256 mismatch: expected $expectedSha256, got $actualHash"
    }
    Move-Item -LiteralPath $partial -Destination $weight
}

$env:UV_CACHE_DIR = $uvCache
$env:HF_HOME = Join-Path $projectRoot "storage\cache\huggingface"
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
if (-not $SkipDependencyInstall) {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        & uv venv --python $projectPython $runtimeRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the isolated faster-whisper environment."
        }
    }
    & uv pip install --python $runtimePython --only-binary ":all:" --torch-backend cpu `
        "faster-whisper==1.2.1" `
        "ctranslate2==4.8.2" `
        "transformers>=4.48,<5" `
        "torch==2.12.1"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the isolated conversion/runtime dependencies."
    }
}

if (-not $SkipConversion) {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        throw "Runtime Python is missing: $runtimePython"
    }
    & $runtimePython (Join-Path $projectRoot "tools\convert_tamil_whisper.py") `
        --source $modelRoot `
        --output $convertedRoot `
        --storage-root (Join-Path $projectRoot "storage") `
        --expected-weight-sha256 $expectedSha256
    if ($LASTEXITCODE -ne 0) {
        throw "CTranslate2 conversion failed."
    }
}

Write-Host "Pinned source: $modelRoot"
Write-Host "Isolated runtime: $runtimeRoot"
if (-not $SkipConversion) {
    Write-Host "Converted INT8 model: $convertedRoot"
}
