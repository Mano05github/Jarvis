param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryId,
    [string]$Revision = "main",
    [string]$CandidateName = "",
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
if ($RepositoryId -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "RepositoryId must be an exact Hugging Face owner/name identifier."
}
if ([string]::IsNullOrWhiteSpace($Revision)) {
    throw "Revision cannot be empty."
}
if ([string]::IsNullOrWhiteSpace($CandidateName)) {
    $CandidateName = $RepositoryId.Replace("/", "--")
}
if ($CandidateName -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "CandidateName may contain only letters, numbers, dot, underscore and hyphen."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$probeRoot = Join-Path $projectRoot "storage\models\llm\candidate-probes"
$target = Join-Path $probeRoot "$CandidateName-source"
$summaryPath = Join-Path $probeRoot "$CandidateName-source.json"
$repository = "https://huggingface.co/$RepositoryId"

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

if ($Offline -and -not (Test-Path -LiteralPath (Join-Path $target ".git"))) {
    throw "Offline inspection requires an existing source checkout: $target"
}
if (-not $Offline -and -not (Test-Path -LiteralPath (Join-Path $target ".git"))) {
    Invoke-GitChecked -Arguments @(
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.required=false",
        "clone", "--depth", "1", "--no-checkout", $repository, $target
    ) | Out-Null
} elseif (-not $Offline) {
    $existingRemote = (Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-C", $target, "remote", "get-url", "origin"
    ) | Select-Object -Last 1).Trim().TrimEnd("/")
    if ($existingRemote -ne $repository) {
        throw "Existing candidate checkout has a different remote: $existingRemote"
    }
}

if (-not $Offline) {
    foreach ($key in @("remote.origin.promisor", "remote.origin.partialclonefilter")) {
        & git -c "safe.directory=$($target.Replace('\', '/'))" -C $target `
            config --local --unset-all $key 2>$null
    }
    Write-Host "Fetching pinned repository metadata; Git LFS weight downloads are disabled..."
    Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-C", $target,
        "fetch", "--depth", "1", "--no-filter", "origin", $Revision
    ) | Out-Null
    Invoke-GitChecked -Arguments @(
        "-c", "safe.directory=$($target.Replace('\', '/'))",
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.required=false",
        "-C", $target,
        "checkout", "--detach", "FETCH_HEAD"
    ) | Out-Null
}
$head = (Invoke-GitChecked -Arguments @(
    "-c", "safe.directory=$($target.Replace('\', '/'))",
    "-C", $target, "rev-parse", "HEAD"
) | Select-Object -Last 1).Trim()
if ($Offline -and $Revision -match '^[0-9a-f]{40}$' -and $head -ne $Revision) {
    throw "Offline checkout revision mismatch: expected $Revision, found $head"
}

$lfsFiles = @()
$ordinaryFiles = @()
Get-ChildItem -LiteralPath $target -Recurse -File | Where-Object {
    $_.FullName -notlike "$(Join-Path $target '.git')*"
} | ForEach-Object {
    $relative = $_.FullName.Substring($target.Length + 1).Replace("\", "/")
    $firstLines = @(Get-Content -LiteralPath $_.FullName -TotalCount 4 -ErrorAction SilentlyContinue)
    if ($firstLines.Count -ge 3 -and $firstLines[0] -eq "version https://git-lfs.github.com/spec/v1") {
        $pointer = $firstLines -join "`n"
        $oidMatch = [regex]::Match($pointer, "oid sha256:([0-9a-f]{64})")
        $sizeMatch = [regex]::Match($pointer, "size ([0-9]+)")
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

$license = $null
$pipeline = $null
$baseModels = @()
$datasets = @()
$readmePath = Join-Path $target "README.md"
if (Test-Path -LiteralPath $readmePath) {
    $readme = Get-Content -Raw -LiteralPath $readmePath
    $licenseMatch = [regex]::Match($readme, "(?m)^license:\s*([^\r\n]+)")
    $pipelineMatch = [regex]::Match($readme, "(?m)^pipeline_tag:\s*([^\r\n]+)")
    if ($licenseMatch.Success) { $license = $licenseMatch.Groups[1].Value.Trim() }
    if ($pipelineMatch.Success) { $pipeline = $pipelineMatch.Groups[1].Value.Trim() }
    foreach ($field in @("base_model", "datasets")) {
        $block = [regex]::Match(
            $readme,
            "(?ms)^$field`:\s*\r?\n((?:\s*-\s*[^\r\n]+\r?\n?)+)"
        )
        $values = @()
        if ($block.Success) {
            $values = @(
                [regex]::Matches($block.Groups[1].Value, "(?m)^\s*-\s*([^\r\n]+)") |
                    ForEach-Object { $_.Groups[1].Value.Trim() }
            )
        } else {
            $scalar = [regex]::Match($readme, "(?m)^$field`:\s*([^\r\n]+)")
            if ($scalar.Success) { $values = @($scalar.Groups[1].Value.Trim()) }
        }
        if ($field -eq "base_model") { $baseModels = $values } else { $datasets = $values }
    }
    if ($datasets.Count -eq 0) {
        $datasetLinks = @(
            [regex]::Matches(
                $readme,
                "https://huggingface\.co/datasets/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
            ) | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
        )
        if ($datasetLinks.Count -gt 0) { $datasets = $datasetLinks }
    }
}

$architectures = @()
$modelType = $null
$autoMap = $null
$configPath = Join-Path $target "config.json"
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
    if ($null -ne $config.architectures) { $architectures = @($config.architectures) }
    if ($null -ne $config.model_type) { $modelType = [string]$config.model_type }
    if ($null -ne $config.auto_map) { $autoMap = $config.auto_map }
}

[Int64]$knownLfsBytes = 0
foreach ($file in $lfsFiles) { $knownLfsBytes += $file.bytes }
$weightPatterns = @("*.safetensors", "*.bin", "*.gguf", "*.pt", "*.pth")
$weightFiles = @($lfsFiles | Where-Object {
    $name = $_.name
    @($weightPatterns | Where-Object { $name -like $_ }).Count -gt 0
})
$remoteCodeFiles = @($ordinaryFiles | Where-Object {
    $_.name -like "*.py" -and $_.name -notlike "examples/*"
})
$warnings = @()
if ([string]::IsNullOrWhiteSpace($license)) { $warnings += "Model card has no declared license." }
if ($baseModels.Count -eq 0) { $warnings += "Model card has no declared base_model." }
if ($datasets.Count -eq 0) { $warnings += "Model card has no declared datasets metadata." }
if ($architectures.Count -eq 0) { $warnings += "config.json has no declared architectures." }
if ($weightFiles.Count -eq 0) { $warnings += "No recognized LFS weight files were found." }
if ($remoteCodeFiles.Count -gt 0 -or $null -ne $autoMap) {
    $warnings += "Repository may require custom remote code; manual review is mandatory."
}

$summary = [ordered]@{
    schema_version = "1.0"
    repository_id = $RepositoryId
    repository = $repository
    requested_revision = $Revision
    pinned_revision = $head
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    license = $license
    pipeline = $pipeline
    base_models = $baseModels
    datasets = $datasets
    architectures = $architectures
    model_type = $modelType
    auto_map = $autoMap
    known_lfs_bytes = $knownLfsBytes
    weight_files = $weightFiles
    lfs_files = $lfsFiles
    ordinary_files = $ordinaryFiles
    remote_code_files = $remoteCodeFiles
    warnings = $warnings
    source_checkout = $target.Substring($projectRoot.Length + 1)
    weights_downloaded = $false
    approved = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $summaryPath

Write-Host "Pinned source revision: $head"
Write-Host "Declared license: $license"
Write-Host "Architectures: $($architectures -join ', ')"
Write-Host "Known LFS bytes (not downloaded): $knownLfsBytes"
Write-Host "Review warnings: $($warnings.Count)"
Write-Host "Source summary: $summaryPath"
