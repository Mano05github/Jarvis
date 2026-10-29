param(
    [string]$Repository = "https://huggingface.co/openai/whisper-large-v3-turbo",
    [string]$Revision = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9",
    [string]$CandidateName = "openai-whisper-large-v3-turbo"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$probeRoot = Join-Path $projectRoot "storage\models\stt\candidate-probes"
$target = Join-Path $probeRoot "$CandidateName-source"
$summaryPath = Join-Path $probeRoot "$CandidateName-source.json"

New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
$env:GIT_LFS_SKIP_SMUDGE = "1"

function Invoke-GitChecked {
    param([string[]]$Arguments)
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed:`n$(@($output | ForEach-Object { "$_" }) -join "`n")"
    }
    return @($output | ForEach-Object { "$_" })
}

if (-not (Test-Path -LiteralPath (Join-Path $target ".git"))) {
    Invoke-GitChecked -Arguments @(
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.required=false",
        "clone", "--depth", "1", "--no-checkout", $Repository, $target
    ) | Out-Null
}

# Hugging Face's partial-clone endpoint can return an invalid lazy-blob pack on
# Windows ("expected packfile"). Repair any existing promisor checkout by
# disabling lazy fetching and refetching the pinned shallow commit normally.
foreach ($key in @("remote.origin.promisor", "remote.origin.partialclonefilter")) {
    & git -c "safe.directory=$($target.Replace('\', '/'))" -C $target `
        config --local --unset-all $key 2>$null
}
Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-C", $target,
    "fetch", "--depth", "1", "--refetch", "--no-filter", "origin", $Revision
) | Out-Null
Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.required=false",
    "-C", $target,
    "checkout", "--detach", $Revision
) | Out-Null
$head = (Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-C", $target,
    "rev-parse", "HEAD"
) | Select-Object -Last 1).Trim()
if ($head -ne $Revision) {
    throw "Checked-out revision mismatch: expected $Revision, got $head"
}

$lfsFiles = @()
$ordinaryFiles = @()
Get-ChildItem -LiteralPath $target -Recurse -File | Where-Object {
    $_.FullName -notlike "$(Join-Path $target '.git')*"
} | ForEach-Object {
    $relative = $_.FullName.Substring($target.Length + 1).Replace("\", "/")
    $firstLines = @(Get-Content -LiteralPath $_.FullName -TotalCount 4 -ErrorAction SilentlyContinue)
    if ($firstLines.Count -ge 3 -and $firstLines[0] -eq "version https://git-lfs.github.com/spec/v1") {
        $oidMatch = [regex]::Match(($firstLines -join "`n"), "oid sha256:([0-9a-f]{64})")
        $sizeMatch = [regex]::Match(($firstLines -join "`n"), "size ([0-9]+)")
        if (-not $oidMatch.Success -or -not $sizeMatch.Success) {
            throw "Malformed Git LFS pointer: $relative"
        }
        $lfsFiles += [ordered]@{
            name = $relative
            bytes = [Int64]$sizeMatch.Groups[1].Value
            sha256 = $oidMatch.Groups[1].Value
        }
    } else {
        $ordinaryFiles += [ordered]@{
            name = $relative
            bytes = $_.Length
        }
    }
}

$readmePath = Join-Path $target "README.md"
$license = $null
$pipeline = $null
$languages = @()
if (Test-Path -LiteralPath $readmePath) {
    $readme = Get-Content -Raw -LiteralPath $readmePath
    $licenseMatch = [regex]::Match($readme, "(?m)^license:\s*([^\r\n]+)")
    $pipelineMatch = [regex]::Match($readme, "(?m)^pipeline_tag:\s*([^\r\n]+)")
    if ($licenseMatch.Success) { $license = $licenseMatch.Groups[1].Value.Trim() }
    if ($pipelineMatch.Success) { $pipeline = $pipelineMatch.Groups[1].Value.Trim() }
    $languageBlock = [regex]::Match($readme, "(?ms)^language:\s*\r?\n((?:\s*-\s*[^\r\n]+\r?\n?)+)")
    if ($languageBlock.Success) {
        $languages = @([regex]::Matches($languageBlock.Groups[1].Value, "(?m)^\s*-\s*([^\r\n]+)") | ForEach-Object {
            $_.Groups[1].Value.Trim()
        })
    }
}

[Int64]$knownLfsBytes = 0
foreach ($file in $lfsFiles) { $knownLfsBytes += $file.bytes }
$summary = [ordered]@{
    schema_version = "1.0"
    repository = $Repository
    revision = $head
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    license = $license
    pipeline = $pipeline
    languages = $languages
    known_lfs_bytes = $knownLfsBytes
    lfs_files = $lfsFiles
    ordinary_files = $ordinaryFiles
    source_checkout = $target.Substring($projectRoot.Length + 1)
    weights_downloaded = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $summaryPath

Write-Host "Pinned source revision: $head"
Write-Host "Declared license: $license"
Write-Host "Known LFS bytes (not downloaded): $knownLfsBytes"
Write-Host "Source summary: $summaryPath"
