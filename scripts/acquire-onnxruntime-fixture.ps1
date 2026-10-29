param(
    [string]$Selection = "config\stt\onnxruntime-source-v1.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$selectionPath = Join-Path $projectRoot $Selection
$fixtureSelection = Join-Path $projectRoot "config\stt\tiny-onnx-fixture-v1.json"
$engineBase = Join-Path $projectRoot "storage\engines\stt\onnxruntime"
$downloadRoot = Join-Path $engineBase "downloads"
$manifestRoot = Join-Path $engineBase "manifests"
$tempBase = Join-Path $projectRoot "storage\temp"

if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
    throw "Run scripts\inspect-onnxruntime-source.ps1 before acquisition."
}
if (-not (Test-Path -LiteralPath $fixtureSelection -PathType Leaf)) {
    throw "Tiny ONNX fixture selection not found: $fixtureSelection"
}
$selected = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json
$fixture = Get-Content -Raw -LiteralPath $fixtureSelection | ConvertFrom-Json
$version = ([string]$selected.release_tag).TrimStart("v")
$targetRoot = Join-Path $engineBase $version
$archivePath = Join-Path $downloadRoot ([string]$selected.asset_name)
$buildManifest = Join-Path $manifestRoot "onnxruntime-$version-build.json"

if ($selected.publisher -ne "Microsoft" -or
    $selected.repository_url -ne "https://github.com/microsoft/onnxruntime" -or
    $selected.platform -ne "windows-x64" -or
    $selected.execution_provider -ne "cpu" -or
    $selected.license_spdx -ne "MIT" -or
    $selected.asset_sha256 -notmatch '^[0-9a-f]{64}$') {
    throw "ONNX Runtime selection is not the approved Microsoft Windows x64 CPU artifact."
}
$assetUri = [Uri][string]$selected.asset_url
if ($assetUri.Scheme -ne "https" -or $assetUri.Host -ne "github.com") {
    throw "ONNX Runtime asset URL must start at official GitHub over HTTPS."
}
if (Test-Path -LiteralPath $targetRoot) {
    throw "Pinned ONNX Runtime target already exists; refusing to overwrite: $targetRoot"
}

$resolvedTempBase = [IO.Path]::GetFullPath($tempBase)
$tempRoot = Join-Path $resolvedTempBase "onnxruntime-acquire-$PID-$([Guid]::NewGuid().ToString('N'))"
$resolvedTempRoot = [IO.Path]::GetFullPath($tempRoot)
if (-not $resolvedTempRoot.StartsWith(
        $resolvedTempBase.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary acquisition directory escaped storage/temp."
}
$tempArchive = Join-Path $resolvedTempRoot ([string]$selected.asset_name)
$extractRoot = Join-Path $resolvedTempRoot "extracted"

New-Item -ItemType Directory -Force -Path $resolvedTempRoot,$extractRoot,$downloadRoot,$manifestRoot | Out-Null
try {
    $curl = Get-Command curl.exe -ErrorAction Stop
    $effectiveUrl = & $curl.Source --fail --location --silent --show-error `
        --proto "=https" --tlsv1.2 --output $tempArchive `
        --write-out "%{url_effective}" ([string]$selected.asset_url)
    if ($LASTEXITCODE -ne 0) { throw "ONNX Runtime archive download failed." }
    $finalUri = [Uri]([string]$effectiveUrl).Trim()
    $allowedFinalHosts = @("github.com", "release-assets.githubusercontent.com")
    if ($finalUri.Scheme -ne "https" -or $finalUri.Host -notin $allowedFinalHosts) {
        throw "ONNX Runtime download redirected to an unapproved host: $($finalUri.Host)"
    }
    $archive = Get-Item -LiteralPath $tempArchive
    if ($archive.Length -ne [int64]$selected.asset_bytes) {
        throw "ONNX Runtime archive size mismatch: expected $($selected.asset_bytes), got $($archive.Length)."
    }
    $archiveSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $tempArchive).Hash.ToLowerInvariant()
    if ($archiveSha -ne [string]$selected.asset_sha256) {
        throw "ONNX Runtime archive SHA-256 mismatch."
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($tempArchive)
    try {
        $entryNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $totalExpandedBytes = [int64]0
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace("\", "/")
            $parts = @($name.Split("/", [StringSplitOptions]::RemoveEmptyEntries))
            if ([string]::IsNullOrWhiteSpace($name) -or
                $name.StartsWith("/") -or $name -match '^[A-Za-z]:' -or
                $parts -contains ".." -or
                -not $name.StartsWith("$($selected.archive_root)/", [StringComparison]::Ordinal)) {
                throw "Unsafe or unexpected ONNX Runtime archive entry: $name"
            }
            $destination = [IO.Path]::GetFullPath((Join-Path $extractRoot $name))
            $resolvedExtract = [IO.Path]::GetFullPath($extractRoot)
            if (-not $destination.StartsWith(
                    $resolvedExtract.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar,
                    [StringComparison]::OrdinalIgnoreCase)) {
                throw "ONNX Runtime archive entry escaped extraction root: $name"
            }
            $totalExpandedBytes += [int64]$entry.Length
            if ($totalExpandedBytes -gt 536870912) {
                throw "ONNX Runtime archive expands beyond the 512-MiB inspection ceiling."
            }
            [void]$entryNames.Add($name)
        }
        foreach ($required in @($selected.required_archive_members)) {
            if (-not $entryNames.Contains([string]$required)) {
                throw "ONNX Runtime archive is missing required member: $required"
            }
        }
    } finally {
        $zip.Dispose()
    }

    Expand-Archive -LiteralPath $tempArchive -DestinationPath $extractRoot
    $extractedRoot = Join-Path $extractRoot ([string]$selected.archive_root)
    if (-not (Test-Path -LiteralPath $extractedRoot -PathType Container)) {
        throw "ONNX Runtime archive root was not extracted as expected."
    }
    foreach ($required in @($selected.required_archive_members)) {
        $relative = ([string]$required).Substring(([string]$selected.archive_root).Length + 1)
        if (-not (Test-Path -LiteralPath (Join-Path $extractedRoot $relative) -PathType Leaf)) {
            throw "Required ONNX Runtime extracted file is missing: $relative"
        }
    }

    Move-Item -LiteralPath $extractedRoot -Destination $targetRoot
    Move-Item -LiteralPath $tempArchive -Destination $archivePath
    $files = @(
        Get-ChildItem -LiteralPath $targetRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
            [ordered]@{
                relative_path = $_.FullName.Substring($targetRoot.Length + 1).Replace("\", "/")
                bytes = [int64]$_.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            }
        }
    )
    $manifest = [ordered]@{
        schema_version = "1.0"
        engine_id = "microsoft-onnxruntime-win-x64-cpu"
        version = $version
        source_commit = [string]$selected.source_commit
        archive_file = "downloads/$($selected.asset_name)"
        archive_bytes = [int64]$selected.asset_bytes
        archive_sha256 = [string]$selected.asset_sha256
        effective_download_host = $finalUri.Host
        license_spdx = "MIT"
        source_selection_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $selectionPath).Hash.ToLowerInvariant()
        fixture_selection_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fixtureSelection).Hash.ToLowerInvariant()
        acquired_at = [DateTimeOffset]::UtcNow.ToString("o")
        activated = $false
        files = $files
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath $buildManifest
    Write-Host "ONNX Runtime acquired and verified without activation."
    Write-Host "Runtime root: $targetRoot"
    Write-Host "Archive SHA-256: $archiveSha"
    Write-Host "Extracted files: $($files.Count)"
    Write-Host "Build manifest: $buildManifest"
} finally {
    if (Test-Path -LiteralPath $resolvedTempRoot) {
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}
