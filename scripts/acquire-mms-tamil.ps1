param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$repositoryId = "facebook/mms-tts-tam"
$revision = "e9cf59dae34f0f51e3b1842876a658e4516f9fe4"
$revisionShort = $revision.Substring(0, 8)
$candidateName = "facebook-mms-tts-tam"
$expectedLicense = "cc-by-nc-4.0"
$sourceProbe = Join-Path $projectRoot "storage\models\tts\candidate-probes\$candidateName-source"
$sourceSummary = Join-Path $projectRoot "storage\models\tts\candidate-probes\$candidateName-source.json"
$modelRoot = Join-Path $projectRoot "storage\models\tts\huggingface\$candidateName-$revisionShort"
$manifestRoot = Join-Path $projectRoot "storage\models\tts\manifests"
$manifestPath = Join-Path $manifestRoot "$candidateName-$revisionShort.json"
$runtimeRoot = Join-Path $projectRoot "storage\engines\tts\mms-vits-transformers-4.57.6-py312"
$runtimePython = Join-Path $runtimeRoot "Scripts\python.exe"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$uvCache = Join-Path $projectRoot "storage\cache\uv"
$tempRoot = Join-Path $projectRoot "storage\temp"

if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Project Python is missing: $projectPython"
}
if (-not (Test-Path -LiteralPath $sourceSummary)) {
    throw "Run scripts\inspect-mms-tamil-source.ps1 before acquisition."
}
$inspected = Get-Content -Raw -LiteralPath $sourceSummary | ConvertFrom-Json
if ($inspected.repository -ne "https://huggingface.co/$repositoryId") {
    throw "Unexpected inspected repository: $($inspected.repository)"
}
if ($inspected.revision -ne $revision) {
    throw "Pinned revision mismatch: expected $revision, found $($inspected.revision)"
}
if ($inspected.license -ne $expectedLicense) {
    throw "Unexpected model license: expected $expectedLicense, found $($inspected.license)"
}
if ($inspected.pipeline -ne "text-to-speech") {
    throw "Unexpected model pipeline: $($inspected.pipeline)"
}
$checkedOutRevision = (& git -c "safe.directory=$($sourceProbe.Replace('\', '/'))" -C $sourceProbe rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $checkedOutRevision -ne $revision) {
    throw "Inspected source checkout does not match the pinned revision."
}

$weightMetadata = @($inspected.lfs_files | Where-Object { $_.name -eq "model.safetensors" })
if ($weightMetadata.Count -ne 1) {
    throw "Pinned source must contain exactly one model.safetensors LFS object."
}
[Int64]$expectedWeightBytes = $weightMetadata[0].bytes
$expectedWeightSha256 = [string]$weightMetadata[0].sha256
if ($expectedWeightBytes -ne 145242872 -or $expectedWeightSha256 -ne "29357e85c7f86f7725b6ff7bab78d1963899c16c2874da1db3a7d6b90f36b050") {
    throw "Pinned SafeTensors metadata differs from the reviewed source."
}

$disk = [System.IO.DriveInfo]::new((Split-Path -Qualifier $projectRoot))
if ($disk.AvailableFreeSpace -lt 2GB) {
    throw "At least 2 GB free space is required for the model, runtime and temporary files."
}
New-Item -ItemType Directory -Force -Path $modelRoot,$manifestRoot,$uvCache,$tempRoot | Out-Null

foreach ($file in $inspected.ordinary_files) {
    $relative = [string]$file.name
    $source = Join-Path $sourceProbe $relative
    $destination = Join-Path $modelRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Pinned source file is missing: $source"
    }
    if ((Get-Item -LiteralPath $source).Length -ne [Int64]$file.bytes) {
        throw "Pinned source file size changed: $source"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$weightDestination = Join-Path $modelRoot "model.safetensors"
$valid = $false
if (Test-Path -LiteralPath $weightDestination) {
    $item = Get-Item -LiteralPath $weightDestination
    if ($item.Length -eq $expectedWeightBytes) {
        $actualHash = (Get-FileHash -LiteralPath $weightDestination -Algorithm SHA256).Hash.ToLowerInvariant()
        $valid = $actualHash -eq $expectedWeightSha256
    }
    if (-not $valid) {
        throw "Existing model weight failed the pinned size/hash check: $weightDestination"
    }
}
if (-not $valid) {
    $partial = "$weightDestination.partial"
    $sourceWeight = Join-Path $sourceProbe "model.safetensors"
    $sourceWeightValid = $false
    if (Test-Path -LiteralPath $sourceWeight) {
        $sourceItem = Get-Item -LiteralPath $sourceWeight
        if ($sourceItem.Length -eq $expectedWeightBytes) {
            $sourceHash = (Get-FileHash -LiteralPath $sourceWeight -Algorithm SHA256).Hash.ToLowerInvariant()
            $sourceWeightValid = $sourceHash -eq $expectedWeightSha256
        }
    }
    if ($sourceWeightValid) {
        Write-Host "Copying the hash-verified SafeTensors weight from the inspected checkout..."
        Copy-Item -LiteralPath $sourceWeight -Destination $partial -Force
    } else {
        $downloadUrl = "https://huggingface.co/$repositoryId/resolve/$revision/model.safetensors?download=true"
        Write-Host "Downloading pinned SafeTensors weight ($expectedWeightBytes bytes)..."
        & curl.exe --location --fail --retry 5 --retry-delay 3 --continue-at - `
            --user-agent "Jarvis-Phase1-MMS-Acquisition/1.0" `
            --output $partial $downloadUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed with curl exit code $LASTEXITCODE"
        }
    }
    $downloaded = Get-Item -LiteralPath $partial
    if ($downloaded.Length -ne $expectedWeightBytes) {
        throw "Downloaded size mismatch: expected $expectedWeightBytes, got $($downloaded.Length)"
    }
    $actualHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedWeightSha256) {
        throw "Downloaded SHA-256 mismatch for model.safetensors"
    }
    Move-Item -LiteralPath $partial -Destination $weightDestination
}

$env:UV_CACHE_DIR = $uvCache
$env:HF_HOME = Join-Path $projectRoot "storage\cache\huggingface"
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
if (-not $SkipDependencyInstall) {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        & uv venv --python $projectPython $runtimeRoot
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the isolated MMS VITS environment." }
    }
    & uv pip install --python $runtimePython --only-binary ":all:" --torch-backend cpu `
        "torch==2.12.1" `
        "transformers==4.57.6" `
        "numpy==2.5.3" `
        "safetensors==0.8.0"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install isolated MMS VITS dependencies." }
}

$manifest = [ordered]@{
    schema_version = "1.0"
    model_id = "$candidateName-$revisionShort"
    function = "tts"
    engine = "transformers-vits"
    version = $revision
    quantization = $null
    languages = @("ta")
    source_url = "https://huggingface.co/$repositoryId/resolve/$revision/model.safetensors"
    source_expected_bytes = $expectedWeightBytes
    source_sha256 = $expectedWeightSha256
    license_name = "CC-BY-NC-4.0 (non-commercial use with attribution)"
    expected_bytes = $expectedWeightBytes
    sha256 = $expectedWeightSha256
    relative_file = "huggingface/$candidateName-$revisionShort/model.safetensors"
    status = "verified"
}
$manifest | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -LiteralPath $manifestPath

Write-Host "Verified model: $modelRoot"
Write-Host "Model manifest: $manifestPath"
Write-Host "Isolated runtime: $runtimeRoot"
Write-Host "License constraint: CC-BY-NC-4.0; non-commercial use with attribution only."
