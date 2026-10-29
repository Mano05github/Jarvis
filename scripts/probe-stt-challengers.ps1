param(
    [string[]]$ModelRepository = @(
        "ai4bharat/indicconformer_stt_ta_hybrid_ctc_rnnt_large",
        "vasista22/whisper-tamil-small",
        "Systran/faster-whisper-small"
    ),
    [switch]$MetadataOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$probeRoot = Join-Path $projectRoot "storage\models\stt\candidate-probes"
$jsonPath = Join-Path $probeRoot "probe-summary.json"
$reportPath = Join-Path $projectRoot "storage\benchmarks\reports\stt-challenger-probe.md"
$uvCache = Join-Path $projectRoot "storage\cache\uv"
$hfCache = Join-Path $projectRoot "storage\cache\huggingface"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python is missing: $python"
}

New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $reportPath) | Out-Null
New-Item -ItemType Directory -Force -Path $uvCache | Out-Null
New-Item -ItemType Directory -Force -Path $hfCache | Out-Null
$env:UV_CACHE_DIR = $uvCache
$env:HF_HOME = $hfCache

$headers = @{ "User-Agent" = "Jarvis-Phase1-Compatibility-Probe/1.0" }
$modelResults = @()

foreach ($repository in $ModelRepository) {
    $repositoryParts = @($repository -split "/", 2)
    if ($repositoryParts.Count -ne 2) {
        throw "Hugging Face repository must have owner/name form: $repository"
    }
    $encoded = "$([Uri]::EscapeDataString($repositoryParts[0]))/$([Uri]::EscapeDataString($repositoryParts[1]))"
    $uri = "https://huggingface.co/api/models/$encoded?blobs=true"
    $safeName = $repository.Replace("/", "--")
    $rawPath = Join-Path $probeRoot "$safeName.api.json"
    try {
        $metadata = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 60
        $metadata | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 -LiteralPath $rawPath

        $files = @()
        [Int64]$totalBytes = 0
        foreach ($sibling in @($metadata.siblings)) {
            [Int64]$size = 0
            $sha256 = $null
            if ($null -ne $sibling.lfs) {
                if ($null -ne $sibling.lfs.size) {
                    $size = [Int64]$sibling.lfs.size
                }
                if ($null -ne $sibling.lfs.sha256) {
                    $sha256 = [string]$sibling.lfs.sha256
                }
            } elseif ($null -ne $sibling.size) {
                $size = [Int64]$sibling.size
            }
            $totalBytes += $size
            $files += [ordered]@{
                name = [string]$sibling.rfilename
                bytes = $size
                sha256 = $sha256
            }
        }

        $license = $null
        if ($null -ne $metadata.cardData -and $null -ne $metadata.cardData.license) {
            $license = [string]$metadata.cardData.license
        }
        if (-not $license) {
            $licenseTag = @($metadata.tags) | Where-Object { $_ -like "license:*" } | Select-Object -First 1
            if ($licenseTag) {
                $license = $licenseTag.Substring("license:".Length)
            }
        }

        $modelResults += [ordered]@{
            repository = $repository
            status = "resolved"
            revision = [string]$metadata.sha
            last_modified = [string]$metadata.lastModified
            library = [string]$metadata.library_name
            pipeline = [string]$metadata.pipeline_tag
            license = $license
            gated = $metadata.gated
            private = [bool]$metadata.private
            disabled = [bool]$metadata.disabled
            total_known_bytes = $totalBytes
            files = $files
            raw_metadata = $rawPath.Substring($projectRoot.Length + 1)
        }
    } catch {
        $modelResults += [ordered]@{
            repository = $repository
            status = "failed"
            error = $_.Exception.Message
        }
    }
}

$resolutions = @()
$requirements = @(
    [ordered]@{ id = "nemo-asr"; requirement = "nemo_toolkit[asr]" },
    [ordered]@{ id = "faster-whisper"; requirement = "faster-whisper" },
    [ordered]@{ id = "onnxruntime"; requirement = "onnxruntime" }
)

if ($MetadataOnly) {
    if (-not (Test-Path -LiteralPath $jsonPath)) {
        throw "Metadata-only mode requires an existing probe summary: $jsonPath"
    }
    $previous = Get-Content -Raw -LiteralPath $jsonPath | ConvertFrom-Json
    $resolutions = @($previous.dependency_resolutions)
} else {
    $uv = Get-Command uv -ErrorAction Stop
    foreach ($item in $requirements) {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            # A failed resolution is an expected probe result. Capture native stderr
            # instead of allowing Windows PowerShell to terminate the whole script.
            $ErrorActionPreference = "Continue"
            $output = & $uv.Source --color never pip install `
                --dry-run `
                --only-binary ":all:" `
                --python $python `
                --python-version "3.12.10" `
                --python-platform "x86_64-pc-windows-msvc" `
                --torch-backend cpu `
                --no-progress `
                $item.requirement 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        $resolutions += [ordered]@{
            id = $item.id
            requirement = $item.requirement
            wheel_only_resolution = if ($exitCode -eq 0) { "passed" } else { "failed" }
            exit_code = $exitCode
            output = (@($output | ForEach-Object { "$_" }) -join "`n")
        }
    }
}

$result = [ordered]@{
    schema_version = "1.0"
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    python = & $python -c "import sys; print(sys.version.split()[0])"
    platform = "x86_64-pc-windows-msvc"
    models = $modelResults
    dependency_resolutions = $resolutions
}
$result | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 -LiteralPath $jsonPath

$lines = @(
    "# STT challenger compatibility probe",
    "",
    "Generated: $($result.generated_at)",
    "",
    "Python: $($result.python)  ",
    "Platform: $($result.platform)",
    "",
    "## Model metadata",
    "",
    "| Repository | Status | Revision | License | Gated | Known bytes | Library |",
    "|---|---|---|---|---|---:|---|"
)
foreach ($model in $modelResults) {
    if ($model.status -eq "resolved") {
        $lines += "| $($model.repository) | resolved | $($model.revision) | $($model.license) | $($model.gated) | $($model.total_known_bytes) | $($model.library) |"
    } else {
        $lines += "| $($model.repository) | failed | - | - | - | - | $($model.error) |"
    }
}
$lines += @(
    "",
    "## Windows Python 3.12 wheel-only resolution",
    "",
    "| Probe | Requirement | Result | Exit code |",
    "|---|---|---|---:|"
)
foreach ($resolution in $resolutions) {
    $lines += "| $($resolution.id) | $($resolution.requirement) | $($resolution.wheel_only_resolution) | $($resolution.exit_code) |"
}
$lines += @(
    "",
    "Full API responses, file hashes/sizes and resolver output are stored in `storage/models/stt/candidate-probes`.",
    "",
    "This probe does not install packages or download model weights. A passing resolver result is necessary but not sufficient for certification."
)
$lines -join "`n" | Set-Content -Encoding utf8 -LiteralPath $reportPath

Write-Host "Probe summary: $jsonPath"
Write-Host "Review report: $reportPath"
