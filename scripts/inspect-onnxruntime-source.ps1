param(
    [string]$Selection = "config\stt\onnxruntime-source-v1.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$selectionPath = Join-Path $projectRoot $Selection
$summaryRoot = Join-Path $projectRoot "storage\engines\stt\onnxruntime\manifests"
$summaryPath = Join-Path $summaryRoot "onnxruntime-source.json"

if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
    throw "ONNX Runtime source selection not found: $selectionPath"
}
$selected = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json
$required = @(
    "schema_version", "source_id", "publisher", "repository_url", "release_tag",
    "release_url", "published_at", "source_commit", "asset_name", "asset_url",
    "asset_bytes", "asset_sha256", "platform", "execution_provider", "license_spdx",
    "license_path", "license_git_sha", "license_bytes", "license_url", "archive_root",
    "required_archive_members", "status"
)
$actual = @($selected.PSObject.Properties.Name | Sort-Object)
$expected = @($required | Sort-Object)
if (($actual -join "`n") -ne ($expected -join "`n")) {
    throw "ONNX Runtime source selection fields differ from the strict schema."
}
if ($selected.publisher -ne "Microsoft" -or
    $selected.repository_url -ne "https://github.com/microsoft/onnxruntime" -or
    $selected.platform -ne "windows-x64" -or
    $selected.execution_provider -ne "cpu" -or
    $selected.license_spdx -ne "MIT" -or
    $selected.status -ne "inspected") {
    throw "ONNX Runtime source selection is not the approved Microsoft Windows x64 CPU source."
}
if ($selected.release_tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$' -or
    $selected.source_commit -notmatch '^[0-9a-f]{40}$' -or
    $selected.asset_sha256 -notmatch '^[0-9a-f]{64}$' -or
    $selected.license_git_sha -notmatch '^[0-9a-f]{40}$') {
    throw "ONNX Runtime source selection has invalid immutable identifiers."
}

$headers = @{
    "User-Agent" = "Jarvis-ONNX-Provenance-Inspector"
    "Accept" = "application/vnd.github+json"
}
$tag = [string]$selected.release_tag
$releaseApi = "https://api.github.com/repos/microsoft/onnxruntime/releases/tags/$tag"
$tagApi = "https://api.github.com/repos/microsoft/onnxruntime/git/ref/tags/$tag"
$licenseApi = "https://api.github.com/repos/microsoft/onnxruntime/contents/LICENSE?ref=$tag"
$repositoryApi = "https://api.github.com/repos/microsoft/onnxruntime"

$release = Invoke-RestMethod -Uri $releaseApi -Headers $headers -TimeoutSec 30
$tagRecord = Invoke-RestMethod -Uri $tagApi -Headers $headers -TimeoutSec 30
$license = Invoke-RestMethod -Uri $licenseApi -Headers $headers -TimeoutSec 30
$repository = Invoke-RestMethod -Uri $repositoryApi -Headers $headers -TimeoutSec 30
$asset = @($release.assets | Where-Object { $_.name -eq $selected.asset_name })

if ($release.draft -or $release.prerelease -or $release.tag_name -ne $tag) {
    throw "Selected ONNX Runtime release is missing, draft, prerelease or mismatched."
}
if ($asset.Count -ne 1) {
    throw "Selected ONNX Runtime asset must resolve exactly once; found $($asset.Count)."
}
$expectedDigest = "sha256:$($selected.asset_sha256)"
if ([int64]$asset[0].size -ne [int64]$selected.asset_bytes -or
    [string]$asset[0].digest -ne $expectedDigest -or
    [string]$asset[0].browser_download_url -ne [string]$selected.asset_url) {
    throw "Official ONNX Runtime release asset metadata does not match the pinned selection."
}
if ($tagRecord.object.type -ne "commit" -or
    $tagRecord.object.sha -ne $selected.source_commit) {
    throw "ONNX Runtime tag does not resolve to the pinned immutable commit."
}
if ($license.sha -ne $selected.license_git_sha -or
    [int64]$license.size -ne [int64]$selected.license_bytes -or
    $license.download_url -ne $selected.license_url -or
    $repository.license.spdx_id -ne "MIT") {
    throw "ONNX Runtime licence metadata does not match the pinned MIT selection."
}

$selectionHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $selectionPath).Hash.ToLowerInvariant()
New-Item -ItemType Directory -Force -Path $summaryRoot | Out-Null
$summary = [ordered]@{
    schema_version = "1.0"
    source_id = [string]$selected.source_id
    release_tag = $tag
    source_commit = [string]$selected.source_commit
    asset_name = [string]$selected.asset_name
    asset_bytes = [int64]$selected.asset_bytes
    asset_sha256 = [string]$selected.asset_sha256
    license_spdx = "MIT"
    license_git_sha = [string]$selected.license_git_sha
    selection_sha256 = $selectionHash
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    downloaded = $false
    activated = $false
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath $summaryPath

Write-Host "Pinned ONNX Runtime release: $tag"
Write-Host "Pinned source commit: $($selected.source_commit)"
Write-Host "Pinned asset: $($selected.asset_name) ($($selected.asset_bytes) bytes)"
Write-Host "Pinned asset SHA-256: $($selected.asset_sha256)"
Write-Host "Declared licence: MIT"
Write-Host "No runtime or model bytes were downloaded or activated."
Write-Host "Source summary: $summaryPath"
