param(
    [string]$Commit = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot "storage\engines\stt\whisper.cpp-src"
$manifestRoot = Join-Path $projectRoot "storage\engines\stt\manifests"
$manifestPath = Join-Path $manifestRoot "whisper.cpp.json"

$git = Get-Command git -ErrorAction Stop
$cmake = Get-Command cmake -ErrorAction Stop

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $sourceRoot) | Out-Null
New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot ".git"))) {
    & $git.Source clone --filter=blob:none --no-checkout `
        https://github.com/ggerganov/whisper.cpp.git $sourceRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to clone the official whisper.cpp repository."
    }
}

Push-Location $sourceRoot
try {
    & $git.Source fetch --depth 1 origin $Commit
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to fetch pinned whisper.cpp commit $Commit"
    }
    & $git.Source checkout --detach $Commit
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to checkout pinned whisper.cpp commit $Commit"
    }
    $actualCommit = (& $git.Source rev-parse HEAD).Trim()
    if ($actualCommit -ne $Commit) {
        throw "Pinned commit mismatch: expected $Commit, got $actualCommit"
    }

    & $cmake.Source -S . -B build `
        -DWHISPER_BUILD_TESTS=OFF `
        -DWHISPER_BUILD_EXAMPLES=ON `
        -DWHISPER_BUILD_SERVER=OFF
    if ($LASTEXITCODE -ne 0) {
        throw "whisper.cpp CMake configuration failed."
    }
    & $cmake.Source --build build --config Release --parallel 4
    if ($LASTEXITCODE -ne 0) {
        throw "whisper.cpp Release build failed."
    }
} finally {
    Pop-Location
}

$whisper = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "build") -Recurse `
    -File -Filter "whisper-cli.exe" | Select-Object -First 1
$quantize = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "build") -Recurse `
    -File -Filter "whisper-quantize.exe" | Select-Object -First 1
if (-not $whisper) {
    throw "Build succeeded but whisper-cli.exe was not found."
}
if (-not $quantize) {
    throw "Build succeeded but whisper-quantize.exe was not found."
}

$manifest = [ordered]@{
    schema_version = "1.0"
    engine_id = "whisper.cpp"
    source_url = "https://github.com/ggerganov/whisper.cpp.git"
    commit = $Commit
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    executable = $whisper.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
    executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $whisper.FullName).Hash.ToLowerInvariant()
    quantize_executable = $quantize.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
    quantize_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $quantize.FullName).Hash.ToLowerInvariant()
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath $manifestPath

Write-Host "whisper.cpp is pinned and built."
Write-Host "CLI: $($whisper.FullName)"
Write-Host "Quantizer: $($quantize.FullName)"
Write-Host "Manifest: $manifestPath"

