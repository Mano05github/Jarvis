param(
    [string]$Revision = "HEAD"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$manifestRoot = Join-Path $projectRoot "storage\engines\llm\manifests"
$summaryPath = Join-Path $manifestRoot "llama.cpp-source.json"
$repository = "https://github.com/ggerganov/llama.cpp.git"

if ([string]::IsNullOrWhiteSpace($Revision)) {
    throw "Revision cannot be empty."
}
$git = Get-Command git -ErrorAction Stop
Write-Host "Resolving llama.cpp revision $Revision..."
$output = & $git.Source ls-remote $repository $Revision 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve llama.cpp revision $Revision`:`n$($output -join "`n")"
}
$matches = @(
    $output | ForEach-Object {
        if ("$_" -match '^([0-9a-f]{40})\s+') { $Matches[1] }
    } | Select-Object -Unique
)
if ($matches.Count -ne 1) {
    throw "Revision must resolve to exactly one commit; found $($matches.Count)."
}
$commit = $matches[0]
New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null
$summary = [ordered]@{
    schema_version = "1.0"
    repository = $repository
    requested_revision = $Revision
    pinned_commit = $commit
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    approved_for = "Jarvis Phase 1 local Qwen semantic-decoder evaluation"
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath $summaryPath
Write-Host "Pinned llama.cpp commit: $commit"
Write-Host "Source summary: $summaryPath"
