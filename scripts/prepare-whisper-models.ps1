param(
    [switch]$RepairInvalid
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceBuild = Join-Path $projectRoot "storage\engines\stt\whisper.cpp-src\build"
$modelRoot = Join-Path $projectRoot "storage\models\stt\whisper.cpp"
$manifestRoot = Join-Path $projectRoot "storage\models\stt\manifests"

$quantize = Get-ChildItem -LiteralPath $sourceBuild -Recurse -File `
    -Filter "whisper-quantize.exe" -ErrorAction Stop | Select-Object -First 1
if (-not $quantize) {
    throw "whisper-quantize.exe was not found. Run acquire-whisper-cpp.ps1 first."
}

New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null

$models = @(
    [ordered]@{
        id = "whisper-base-multilingual-q5_0"
        source_name = "ggml-base.bin"
        output_name = "ggml-base-q5_0.bin"
        source_bytes = 147951465
        source_sha256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
    },
    [ordered]@{
        id = "whisper-small-multilingual-q5_0"
        source_name = "ggml-small.bin"
        output_name = "ggml-small-q5_0.bin"
        source_bytes = 487601967
        source_sha256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
    }
)

foreach ($model in $models) {
    $sourceUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$($model.source_name)"
    $sourcePath = Join-Path $modelRoot $model.source_name
    $outputPath = Join-Path $modelRoot $model.output_name

    if (Test-Path -LiteralPath $sourcePath) {
        $source = Get-Item -LiteralPath $sourcePath
        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
        $sourceIsValid = ($source.Length -eq $model.source_bytes) -and ($sourceHash -eq $model.source_sha256)
        if (-not $sourceIsValid) {
            if (-not $RepairInvalid) {
                throw "Invalid source model: $sourcePath. Expected $($model.source_bytes) bytes and SHA-256 $($model.source_sha256), got $($source.Length) bytes and $sourceHash. Re-run with -RepairInvalid to quarantine and replace it."
            }

            $quarantine = Join-Path $projectRoot "storage\temp\rejected-models\$(Get-Date -Format 'yyyyMMddTHHmmss')"
            New-Item -ItemType Directory -Force -Path $quarantine | Out-Null
            Move-Item -LiteralPath $sourcePath -Destination $quarantine
            if (Test-Path -LiteralPath $outputPath) {
                Move-Item -LiteralPath $outputPath -Destination $quarantine
            }
            Write-Warning "Quarantined invalid model files under $quarantine"
        }
    }

    if (-not (Test-Path -LiteralPath $sourcePath)) {
        Write-Host "Downloading $($model.source_name) into Jarvis storage..."
        $partialPath = "$sourcePath.partial"
        Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -Uri $sourceUrl -OutFile $partialPath
        $download = Get-Item -LiteralPath $partialPath
        $downloadHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $partialPath).Hash.ToLowerInvariant()
        if (($download.Length -ne $model.source_bytes) -or ($downloadHash -ne $model.source_sha256)) {
            throw "Downloaded model failed integrity validation: $partialPath"
        }
        Move-Item -LiteralPath $partialPath -Destination $sourcePath
    }
    if (-not (Test-Path -LiteralPath $outputPath)) {
        & $quantize.FullName $sourcePath $outputPath q5_0
        if ($LASTEXITCODE -ne 0) {
            throw "Quantization failed for $($model.source_name)"
        }
    }

    $output = Get-Item -LiteralPath $outputPath
    $manifest = [ordered]@{
        schema_version = "1.0"
        model_id = $model.id
        function = "stt"
        engine = "whisper.cpp"
        version = "pinned-local-build"
        quantization = "q5_0"
        languages = @("ta", "en")
        source_url = $sourceUrl
        source_expected_bytes = $model.source_bytes
        source_sha256 = $model.source_sha256
        license_name = "MIT (verify against the pinned source/model card before certification)"
        expected_bytes = $output.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $outputPath).Hash.ToLowerInvariant()
        relative_file = "whisper.cpp/$($model.output_name)"
        status = "downloaded"
    }
    $manifestPath = Join-Path $manifestRoot "$($model.id).json"
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath $manifestPath
    Write-Host "Recorded local hash (not yet certified): $outputPath"
    Write-Host "Manifest: $manifestPath"
}

