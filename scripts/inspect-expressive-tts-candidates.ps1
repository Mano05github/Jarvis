$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$probeRoot = Join-Path $projectRoot "storage\models\tts\candidate-probes"
$env:GIT_LFS_SKIP_SMUDGE = "1"

$candidates = @(
    [ordered]@{
        name = "ai4bharat-indicf5"
        repository = "https://github.com/AI4Bharat/IndicF5.git"
        revision = "13f7c4d627cc10111aea8fe9c0039462cacacdc7"
    },
    [ordered]@{
        name = "ai4bharat-indic-tts"
        repository = "https://github.com/AI4Bharat/Indic-TTS.git"
        revision = "ad2461c22c373f89a140c5d9fb617b101219bdad"
    },
    [ordered]@{
        name = "huggingface-parler-tts"
        repository = "https://github.com/huggingface/parler-tts.git"
        revision = "d108732cd57788ec86bc857d99a6cabd66663d68"
    }
)

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
foreach ($candidate in $candidates) {
    $target = Join-Path $probeRoot "$($candidate.name)-source"
    $summaryPath = Join-Path $probeRoot "$($candidate.name)-source.json"
    if (-not (Test-Path -LiteralPath (Join-Path $target ".git"))) {
        Invoke-GitChecked -Arguments @(
            "-c", "filter.lfs.smudge=",
            "-c", "filter.lfs.required=false",
            "clone", "--no-checkout", $candidate.repository, $target
        ) | Out-Null
    }
    Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-C", $target,
        "fetch", "--depth", "1", "origin", $candidate.revision
    ) | Out-Null
    Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.required=false",
        "-C", $target,
        "checkout", "--detach", $candidate.revision
    ) | Out-Null
    $head = (Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-C", $target,
        "rev-parse", "HEAD"
    ) | Select-Object -Last 1).Trim()
    if ($head -ne $candidate.revision) {
        throw "Pinned revision mismatch for $($candidate.name): $head"
    }

    $readmePath = Join-Path $target "README.md"
    $readme = if (Test-Path -LiteralPath $readmePath) {
        Get-Content -Raw -LiteralPath $readmePath
    } else { "" }
    $licenseFiles = @(Get-ChildItem -LiteralPath $target -File -Force | Where-Object {
        $_.Name -match "(?i)^(license|copying)"
    } | ForEach-Object {
        [ordered]@{
            name = $_.Name
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    $dependencyFiles = @(Get-ChildItem -LiteralPath $target -Recurse -File -Force | Where-Object {
        $_.FullName -notlike "$(Join-Path $target '.git')*" -and
        $_.Name -match "^(requirements.*\.txt|pyproject\.toml|environment.*\.ya?ml|setup\.py)$"
    } | ForEach-Object {
        [ordered]@{
            name = $_.FullName.Substring($target.Length + 1).Replace("\", "/")
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    $summary = [ordered]@{
        schema_version = "1.0"
        candidate = $candidate.name
        repository = $candidate.repository
        revision = $head
        inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
        code_license_files = $licenseFiles
        dependency_files = $dependencyFiles
        readme_evidence = [ordered]@{
            tamil = [bool]($readme -match "(?i)\btamil\b|\btam\b")
            english = [bool]($readme -match "(?i)\benglish\b")
            code_switch = [bool]($readme -match "(?i)code[- ]?switch|tanglish|mixed[- ]language")
            expressive = [bool]($readme -match "(?i)expressive|emotion|prosody|style prompt|voice prompt")
            local_inference = [bool]($readme -match "(?i)inference|infer|synthesi[sz]")
        }
        weights_downloaded = $false
        manual_review_required = $true
    }
    $summary | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $summaryPath

    Write-Host "Pinned $($candidate.name): $head"
    Write-Host "Summary: $summaryPath"
    Write-Host ($summary.readme_evidence | ConvertTo-Json -Compress)
}
