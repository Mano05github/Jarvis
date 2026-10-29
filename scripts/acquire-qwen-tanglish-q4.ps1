param(
    [int]$MinimumFreeGB = 45,
    [switch]$SkipDependencyInstall,
    [switch]$SkipDownload,
    [switch]$SkipConversion
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$repositoryId = "sugiv/Qwen3-8B-Tanglish"
$revision = "015825088f2f7bb73fa2ae5efa148365841ebadd"
$revisionShort = $revision.Substring(0, 8)
$candidateName = "sugiv--Qwen3-8B-Tanglish"
$probeRoot = Join-Path $projectRoot "storage\models\llm\candidate-probes"
$sourceProbe = Join-Path $probeRoot "$candidateName-source"
$sourceSummary = Join-Path $probeRoot "$candidateName-source.json"
$modelRoot = Join-Path $projectRoot "storage\models\llm\huggingface\$candidateName-$revisionShort"
$ggufRoot = Join-Path $projectRoot "storage\models\llm\gguf"
$manifestRoot = Join-Path $projectRoot "storage\models\llm\manifests"
$bf16Model = Join-Path $ggufRoot "$candidateName-$revisionShort-BF16.gguf"
$q4Model = Join-Path $ggufRoot "$candidateName-$revisionShort-Q4_K_M.gguf"
$manifestPath = Join-Path $manifestRoot "$candidateName-$revisionShort-Q4_K_M.json"
$provenancePath = Join-Path $manifestRoot "$candidateName-$revisionShort-Q4_K_M.provenance.json"
$llamaBuildManifest = Join-Path $projectRoot "storage\engines\llm\manifests\llama.cpp-build.json"
$conversionRuntime = Join-Path $projectRoot "storage\engines\llm\llama-cpp-convert-py312"
$conversionPython = Join-Path $conversionRuntime "Scripts\python.exe"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$uvCache = Join-Path $projectRoot "storage\cache\uv"
$tempRoot = Join-Path $projectRoot "storage\temp"

if (-not (Test-Path -LiteralPath $sourceSummary -PathType Leaf)) {
    throw "Run scripts\inspect-qwen-tanglish-source.ps1 before acquisition."
}
if (-not (Test-Path -LiteralPath $llamaBuildManifest -PathType Leaf)) {
    throw "Build pinned llama.cpp with scripts\acquire-llama-cpp.ps1 first."
}
if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) {
    throw "Project Python 3.12.10 is missing: $projectPython"
}
$inspected = Get-Content -Raw -LiteralPath $sourceSummary | ConvertFrom-Json
if ($inspected.repository_id -ne $repositoryId) { throw "Unexpected repository ID." }
if ($inspected.pinned_revision -ne $revision) { throw "Pinned Qwen revision mismatch." }
if ($inspected.license -ne "apache-2.0") { throw "Unexpected Qwen license." }
if (@($inspected.datasets) -notcontains "sugiv/tanglish-pairs-v1") {
    throw "The inspected source does not record the declared Tanglish training corpus. Rerun inspection."
}
$checkedOutRevision = (& git -c "safe.directory=$($sourceProbe.Replace('\', '/'))" `
    -C $sourceProbe rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $checkedOutRevision -ne $revision) {
    throw "Inspected Qwen source checkout does not match the pinned revision."
}

$llama = Get-Content -Raw -LiteralPath $llamaBuildManifest | ConvertFrom-Json
$llamaSource = Join-Path $projectRoot "storage\engines\llm\llama.cpp-src"
$converter = Join-Path $llamaSource "convert_hf_to_gguf.py"
$quantize = Join-Path $projectRoot ([string]$llama.quantize_executable).Replace('/', '\')
if (-not (Test-Path -LiteralPath $converter -PathType Leaf)) { throw "GGUF converter is missing." }
if (-not (Test-Path -LiteralPath $quantize -PathType Leaf)) { throw "llama quantizer is missing." }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $quantize).Hash.ToLowerInvariant() -ne $llama.quantize_sha256) {
    throw "llama quantizer hash does not match its build manifest."
}

$disk = [System.IO.DriveInfo]::new((Split-Path -Qualifier $projectRoot))
if ($MinimumFreeGB -lt 1 -or $disk.AvailableFreeSpace -lt ($MinimumFreeGB * 1GB)) {
    throw "At least $MinimumFreeGB GB free space is required for BF16 source, GGUF and Q4 conversion."
}
New-Item -ItemType Directory -Force -Path `
    $modelRoot,$ggufRoot,$manifestRoot,$uvCache,$tempRoot | Out-Null

$requiredFiles = @(
    "added_tokens.json",
    "chat_template.jinja",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors.index.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "model-00001-of-00004.safetensors",
    "model-00002-of-00004.safetensors",
    "model-00003-of-00004.safetensors",
    "model-00004-of-00004.safetensors"
)

foreach ($name in $requiredFiles) {
    $destination = Join-Path $modelRoot $name
    $lfsMetadata = @($inspected.lfs_files | Where-Object { $_.name -eq $name })
    if ($lfsMetadata.Count -gt 1) { throw "Duplicate LFS metadata for $name" }
    if ($lfsMetadata.Count -eq 0) {
        $source = Join-Path $sourceProbe $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Pinned ordinary source file is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
        continue
    }
    [Int64]$expectedBytes = $lfsMetadata[0].bytes
    $expectedSha256 = [string]$lfsMetadata[0].sha256
    $valid = $false
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $item = Get-Item -LiteralPath $destination
        if ($item.Length -eq $expectedBytes) {
            $actualHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
            $valid = $actualHash -eq $expectedSha256
        }
        if (-not $valid) { throw "Existing source file failed validation: $destination" }
    }
    if ($valid) { continue }
    if ($SkipDownload) { throw "Required pinned source file is absent: $destination" }
    $partial = "$destination.partial"
    $urlName = $name.Replace('\', '/')
    $downloadUrl = "https://huggingface.co/$repositoryId/resolve/$revision/$urlName`?download=true"
    Write-Host "Downloading pinned $name ($expectedBytes bytes)..."
    & curl.exe --location --fail --retry 5 --retry-delay 3 --continue-at - `
        --user-agent "Jarvis-Phase1-QwenAcquisition/1.0" `
        --output $partial $downloadUrl
    if ($LASTEXITCODE -ne 0) { throw "Download failed for $name." }
    $downloaded = Get-Item -LiteralPath $partial
    if ($downloaded.Length -ne $expectedBytes) { throw "Downloaded size mismatch for $name." }
    $actualHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedSha256) { throw "Downloaded SHA-256 mismatch for $name." }
    Move-Item -LiteralPath $partial -Destination $destination
}

$env:UV_CACHE_DIR = $uvCache
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
if (-not $SkipDependencyInstall) {
    if (-not (Test-Path -LiteralPath $conversionPython -PathType Leaf)) {
        & uv venv --python $projectPython $conversionRuntime
        if ($LASTEXITCODE -ne 0) { throw "Unable to create the isolated conversion environment." }
    }
    $requirements = @(
        (Join-Path $llamaSource "requirements\requirements-convert_hf_to_gguf.txt"),
        (Join-Path $llamaSource "requirements.txt")
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $requirements) { throw "llama.cpp conversion requirements file was not found." }
    & uv pip install --python $conversionPython --requirement $requirements
    if ($LASTEXITCODE -ne 0) { throw "Unable to install llama.cpp conversion requirements." }
}

if (-not $SkipConversion) {
    if (-not (Test-Path -LiteralPath $conversionPython -PathType Leaf)) {
        throw "Conversion Python is missing: $conversionPython"
    }
    if (-not (Test-Path -LiteralPath $bf16Model -PathType Leaf)) {
        & $conversionPython $converter $modelRoot --outfile $bf16Model --outtype bf16
        if ($LASTEXITCODE -ne 0) { throw "BF16 GGUF conversion failed." }
    }
    if (-not (Test-Path -LiteralPath $q4Model -PathType Leaf)) {
        & $quantize $bf16Model $q4Model Q4_K_M 4
        if ($LASTEXITCODE -ne 0) { throw "Q4_K_M quantization failed." }
    }
}

if (-not $SkipConversion) {
    $q4Item = Get-Item -LiteralPath $q4Model
    if ($q4Item.Length -lt 3GB -or $q4Item.Length -gt 8GB) {
        throw "Q4_K_M output size is outside the expected 3-8 GB safety range."
    }
    $sourceWeights = @(
        $inspected.lfs_files | Where-Object { $_.name -match '^model-\d+-of-\d+\.safetensors$' } |
            ForEach-Object { [ordered]@{ name = $_.name; bytes = $_.bytes; sha256 = $_.sha256 } }
    )
    $manifest = [ordered]@{
        schema_version = "1.0"
        model_id = "qwen3-8b-tanglish-q4-k-m"
        function = "llm"
        engine = "llama.cpp"
        version = $revision
        quantization = "Q4_K_M"
        languages = @("ta-Latn", "en")
        source_url = "https://huggingface.co/$repositoryId/tree/$revision"
        source_expected_bytes = $null
        source_sha256 = $null
        license_name = "apache-2.0"
        expected_bytes = $q4Item.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $q4Model).Hash.ToLowerInvariant()
        relative_file = "gguf/$candidateName-$revisionShort-Q4_K_M.gguf"
        status = "verified"
    }
    $provenance = [ordered]@{
        schema_version = "1.0"
        model_id = "qwen3-8b-tanglish-q4-k-m"
        repository_id = $repositoryId
        revision = $revision
        license = "apache-2.0"
        training_dataset = "sugiv/tanglish-pairs-v1"
        source_weights = $sourceWeights
        llama_cpp_commit = $llama.commit
        quantization = "Q4_K_M"
        context_size = 2048
        converted_at = [DateTimeOffset]::UtcNow.ToString("o")
        gguf_file = $q4Model.Substring($projectRoot.Length + 1).Replace("\", "/")
        gguf_bytes = $q4Item.Length
        gguf_sha256 = $manifest.sha256
        intermediate_bf16_file = $bf16Model.Substring($projectRoot.Length + 1).Replace("\", "/")
        intermediate_bf16_bytes = (Get-Item -LiteralPath $bf16Model).Length
    }
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -LiteralPath $manifestPath
    $provenance | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -LiteralPath $provenancePath
    Write-Host "Q4_K_M model: $q4Model"
    Write-Host "Model bytes: $($q4Item.Length)"
    Write-Host "Model SHA-256: $($manifest.sha256)"
    Write-Host "Model manifest: $manifestPath"
    Write-Host "Conversion provenance: $provenancePath"
}
