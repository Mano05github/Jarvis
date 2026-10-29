param(
    [string]$Repository = "https://huggingface.co/ai4bharat/IndicF5",
    [string]$CandidateName = "ai4bharat-indicf5-model"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$probeRoot = Join-Path $projectRoot "storage\models\tts\candidate-probes"
$target = Join-Path $probeRoot "$CandidateName-source"
$summaryPath = Join-Path $probeRoot "$CandidateName-source.json"
$env:GIT_LFS_SKIP_SMUDGE = "1"
$env:GIT_TERMINAL_PROMPT = "0"

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

New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
$anonymousGit = @("-c", "credential.helper=", "-c", "credential.interactive=never")
$headArguments = $anonymousGit + @("ls-remote", $Repository, "HEAD")
$headLine = Invoke-GitChecked -Arguments $headArguments | Select-Object -Last 1
$revision = ([string]$headLine -split "\s+")[0].Trim()
if ($revision -notmatch "^[0-9a-f]{40}$") {
    throw "Could not resolve an immutable 40-character model revision from: $headLine"
}
if (-not (Test-Path -LiteralPath (Join-Path $target ".git"))) {
    $cloneArguments = $anonymousGit + @(
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.required=false",
        "clone", "--no-checkout", $Repository, $target
    )
    Invoke-GitChecked -Arguments $cloneArguments | Out-Null
}
$fetchArguments = $anonymousGit + @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-C", $target,
    "fetch", "--depth", "1", "origin", $revision
)
Invoke-GitChecked -Arguments $fetchArguments | Out-Null
Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.required=false",
    "-C", $target,
    "checkout", "--detach", $revision
) | Out-Null
$head = (Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-C", $target,
    "rev-parse", "HEAD"
) | Select-Object -Last 1).Trim()
if ($head -ne $revision) { throw "Model checkout revision mismatch: $head" }

$lfsFiles = @()
$ordinaryFiles = @()
Get-ChildItem -LiteralPath $target -Recurse -File -Force | Where-Object {
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
        $ordinaryFiles += [ordered]@{ name = $relative; bytes = $_.Length }
    }
}

$readmePath = Join-Path $target "README.md"
$readme = if (Test-Path -LiteralPath $readmePath) {
    Get-Content -Raw -LiteralPath $readmePath
} else { "" }
$declaredLicense = $null
$licenseMatch = [regex]::Match($readme, "(?m)^license:\s*([^\r\n]+)")
if ($licenseMatch.Success) { $declaredLicense = $licenseMatch.Groups[1].Value.Trim() }
$licenseFiles = @(Get-ChildItem -LiteralPath $target -File -Force | Where-Object {
    $_.Name -match "(?i)^(license|copying)"
} | ForEach-Object {
    [ordered]@{
        name = $_.Name
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$pythonFiles = @($ordinaryFiles | Where-Object { $_.name -match "\.py$" } | Select-Object -ExpandProperty name)
$configPath = Join-Path $target "config.json"
$autoMap = $null
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
    if ($null -ne $config.auto_map) { $autoMap = $config.auto_map }
}
[Int64]$knownLfsBytes = 0
foreach ($file in $lfsFiles) { $knownLfsBytes += $file.bytes }

$summary = [ordered]@{
    schema_version = "1.0"
    repository = $Repository
    revision = $head
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    declared_model_license = $declaredLicense
    license_files = $licenseFiles
    known_lfs_bytes = $knownLfsBytes
    lfs_files = $lfsFiles
    ordinary_files = $ordinaryFiles
    custom_python_files = $pythonFiles
    auto_map = $autoMap
    readme_evidence = [ordered]@{
        tamil = [bool]($readme -match "(?i)\btamil\b|\btam\b")
        english = [bool]($readme -match "(?i)\benglish\b")
        code_switch = [bool]($readme -match "(?i)code[- ]?switch|tanglish|mixed[- ]language")
        expressive = [bool]($readme -match "(?i)expressive|emotion|prosody|style|description prompt")
        reference_audio = [bool]($readme -match "(?i)reference prompt audio|ref_audio|reference audio")
    }
    weights_downloaded = $false
    remote_code_review_required = $pythonFiles.Count -gt 0 -or $null -ne $autoMap
}
$summary | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 -LiteralPath $summaryPath

Write-Host "Pinned $CandidateName revision: $head"
Write-Host "Declared model license: $declaredLicense"
Write-Host "Known LFS bytes (not downloaded): $knownLfsBytes"
Write-Host "Custom Python files: $($pythonFiles.Count)"
Write-Host "Summary: $summaryPath"
Write-Host ($summary.readme_evidence | ConvertTo-Json -Compress)
