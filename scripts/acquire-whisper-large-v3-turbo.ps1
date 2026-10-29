param(
    [string]$Revision = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9",
    [string]$RepositoryId = "openai/whisper-large-v3-turbo",
    [string]$CandidateName = "openai-whisper-large-v3-turbo",
    [string]$ExpectedLicense = "mit",
    [int]$MinimumFreeGB = 10,
    [switch]$SkipDependencyInstall,
    [switch]$SkipConversion
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$revisionShort = $Revision.Substring(0, 8)
$sourceProbe = Join-Path $projectRoot "storage\models\stt\candidate-probes\$CandidateName-source"
$sourceSummary = Join-Path $projectRoot "storage\models\stt\candidate-probes\$CandidateName-source.json"
$modelRoot = Join-Path $projectRoot "storage\models\stt\huggingface\$CandidateName-$revisionShort"
$convertedRoot = Join-Path $projectRoot "storage\models\stt\ctranslate2\$CandidateName-$revisionShort-int8"
$runtimeRoot = Join-Path $projectRoot "storage\engines\stt\faster-whisper-1.2.1-py312"
$runtimePython = Join-Path $runtimeRoot "Scripts\python.exe"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$uvCache = Join-Path $projectRoot "storage\cache\uv"
$tempRoot = Join-Path $projectRoot "storage\temp"
$weightName = "model.safetensors"

if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Project Python is missing: $projectPython"
}
if (-not (Test-Path -LiteralPath $sourceSummary)) {
    throw "Run scripts\inspect-whisper-large-v3-turbo-source.ps1 before acquisition."
}
$inspected = Get-Content -Raw -LiteralPath $sourceSummary | ConvertFrom-Json
if ($inspected.repository -ne "https://huggingface.co/$RepositoryId") {
    throw "Unexpected inspected repository: $($inspected.repository)"
}
if ($inspected.revision -ne $Revision) {
    throw "Pinned revision mismatch: expected $Revision, found $($inspected.revision)"
}
if ($inspected.license -ne $ExpectedLicense) {
    throw "Unexpected model license: expected $ExpectedLicense, found $($inspected.license)"
}
$checkedOutRevision = (& git -c "safe.directory=$($sourceProbe.Replace('\', '/'))" -C $sourceProbe rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $checkedOutRevision -ne $Revision) {
    throw "Inspected source checkout does not match the pinned revision."
}

$weightMetadata = @($inspected.lfs_files | Where-Object { $_.name -eq $weightName })
if ($weightMetadata.Count -ne 1) {
    throw "Pinned source must contain exactly one $weightName LFS object."
}
$expectedWeightBytes = [Int64]$weightMetadata[0].bytes
$expectedWeightSha256 = [string]$weightMetadata[0].sha256

$disk = [System.IO.DriveInfo]::new((Split-Path -Qualifier $projectRoot))
if ($MinimumFreeGB -lt 1 -or $disk.AvailableFreeSpace -lt ($MinimumFreeGB * 1GB)) {
    throw "At least $MinimumFreeGB GB free space is required for source weights, conversion and temporary files."
}

New-Item -ItemType Directory -Force -Path $modelRoot,$uvCache,$tempRoot | Out-Null
$requiredFiles = @(
    "added_tokens.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "normalizer.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    $weightName
)

foreach ($name in $requiredFiles) {
    $destination = Join-Path $modelRoot $name
    $lfsMetadata = @($inspected.lfs_files | Where-Object { $_.name -eq $name })
    if ($lfsMetadata.Count -gt 1) {
        throw "Duplicate LFS metadata for $name"
    }
    if ($lfsMetadata.Count -eq 0) {
        $source = Join-Path $sourceProbe $name
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Pinned ordinary source file is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
        continue
    }

    [Int64]$expectedBytes = $lfsMetadata[0].bytes
    $expectedSha256 = [string]$lfsMetadata[0].sha256
    $valid = $false
    if (Test-Path -LiteralPath $destination) {
        $item = Get-Item -LiteralPath $destination
        if ($item.Length -eq $expectedBytes) {
            $actualHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
            $valid = $actualHash -eq $expectedSha256
        }
        if (-not $valid) {
            throw "Existing source file failed the pinned size/hash check: $destination"
        }
    }
    if ($valid) { continue }

    $partial = "$destination.partial"
    $downloadUrl = "https://huggingface.co/$RepositoryId/resolve/$Revision/$name`?download=true"
    Write-Host "Downloading pinned $name ($expectedBytes bytes)..."
    & curl.exe --location --fail --retry 5 --retry-delay 3 --continue-at - `
        --user-agent "Jarvis-Phase1-WhisperAcquisition/1.0" `
        --output $partial $downloadUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed for $name with curl exit code $LASTEXITCODE"
    }
    $downloaded = Get-Item -LiteralPath $partial
    if ($downloaded.Length -ne $expectedBytes) {
        throw "Downloaded size mismatch for $name`: expected $expectedBytes, got $($downloaded.Length)"
    }
    $actualHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedSha256) {
        throw "Downloaded SHA-256 mismatch for $name"
    }
    Move-Item -LiteralPath $partial -Destination $destination
}

$readmeSource = Join-Path $sourceProbe "README.md"
if (Test-Path -LiteralPath $readmeSource) {
    Copy-Item -LiteralPath $readmeSource -Destination (Join-Path $modelRoot "README.md") -Force
}

$env:UV_CACHE_DIR = $uvCache
$env:HF_HOME = Join-Path $projectRoot "storage\cache\huggingface"
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
if (-not $SkipDependencyInstall) {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        & uv venv --python $projectPython $runtimeRoot
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the isolated faster-whisper environment." }
    }
    & uv pip install --python $runtimePython --only-binary ":all:" --torch-backend cpu `
        "faster-whisper==1.2.1" `
        "ctranslate2==4.8.2" `
        "transformers>=4.48,<5" `
        "torch==2.12.1"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install the isolated conversion/runtime dependencies." }
}

if (-not $SkipConversion) {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        throw "Runtime Python is missing: $runtimePython"
    }
    & $runtimePython (Join-Path $projectRoot "tools\convert_whisper_ct2.py") `
        --source $modelRoot `
        --output $convertedRoot `
        --storage-root (Join-Path $projectRoot "storage") `
        --weight-file $weightName `
        --expected-weight-sha256 $expectedWeightSha256
    if ($LASTEXITCODE -ne 0) { throw "CTranslate2 conversion failed." }
}

Write-Host "Pinned source: $modelRoot"
Write-Host "Source weight: $expectedWeightBytes bytes, SHA-256 $expectedWeightSha256"
Write-Host "Isolated runtime: $runtimeRoot"
if (-not $SkipConversion) { Write-Host "Converted INT8 model: $convertedRoot" }
