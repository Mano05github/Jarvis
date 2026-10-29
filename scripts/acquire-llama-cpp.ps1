param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$engineRoot = Join-Path $projectRoot "storage\engines\llm"
$sourceRoot = Join-Path $engineRoot "llama.cpp-src"
$manifestRoot = Join-Path $engineRoot "manifests"
$sourceSummary = Join-Path $manifestRoot "llama.cpp-source.json"
$buildManifest = Join-Path $manifestRoot "llama.cpp-build.json"
$repository = "https://github.com/ggerganov/llama.cpp.git"

if (-not (Test-Path -LiteralPath $sourceSummary -PathType Leaf)) {
    throw "Run scripts\inspect-llama-cpp-source.ps1 before acquisition."
}
$inspected = Get-Content -Raw -LiteralPath $sourceSummary | ConvertFrom-Json
if ($inspected.repository -ne $repository -or $inspected.pinned_commit -notmatch '^[0-9a-f]{40}$') {
    throw "Invalid llama.cpp source summary: $sourceSummary"
}
$commit = [string]$inspected.pinned_commit
$git = Get-Command git -ErrorAction Stop
$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
if ($cmakeCommand) {
    $cmakeExe = $cmakeCommand.Source
} else {
    $defaultCmake = "C:\Program Files\CMake\bin\cmake.exe"
    if (-not (Test-Path -LiteralPath $defaultCmake -PathType Leaf)) {
        throw "CMake is required and was not found on PATH or at $defaultCmake"
    }
    $cmakeExe = $defaultCmake
}
New-Item -ItemType Directory -Force -Path $engineRoot,$manifestRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot ".git"))) {
    & $git.Source clone --filter=blob:none --no-checkout $repository $sourceRoot
    if ($LASTEXITCODE -ne 0) { throw "Unable to clone llama.cpp." }
}
$safeRoot = $sourceRoot.Replace('\', '/')
& $git.Source -c "safe.directory=$safeRoot" -C $sourceRoot fetch --depth 1 origin $commit
if ($LASTEXITCODE -ne 0) { throw "Unable to fetch pinned llama.cpp commit $commit" }
& $git.Source -c "safe.directory=$safeRoot" -C $sourceRoot checkout --detach $commit
if ($LASTEXITCODE -ne 0) { throw "Unable to checkout pinned llama.cpp commit $commit" }
$actualCommit = (& $git.Source -c "safe.directory=$safeRoot" -C $sourceRoot rev-parse HEAD).Trim()
if ($actualCommit -ne $commit) { throw "llama.cpp commit verification failed." }

& $cmakeExe -S $sourceRoot -B (Join-Path $sourceRoot "build") `
    -DLLAMA_BUILD_TESTS=OFF `
    -DLLAMA_BUILD_EXAMPLES=OFF `
    -DLLAMA_BUILD_SERVER=ON `
    -DGGML_OPENMP=ON
if ($LASTEXITCODE -ne 0) { throw "llama.cpp CMake configuration failed." }
& $cmakeExe --build (Join-Path $sourceRoot "build") --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw "llama.cpp Release build failed." }

$server = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "build") -Recurse `
    -File -Filter "llama-server.exe" | Select-Object -First 1
$quantize = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "build") -Recurse `
    -File -Filter "llama-quantize.exe" | Select-Object -First 1
if (-not $server) { throw "Build succeeded but llama-server.exe was not found." }
if (-not $quantize) { throw "Build succeeded but llama-quantize.exe was not found." }

$manifest = [ordered]@{
    schema_version = "1.0"
    engine_id = "llama.cpp"
    repository = $repository
    commit = $commit
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    server_executable = $server.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
    server_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $server.FullName).Hash.ToLowerInvariant()
    quantize_executable = $quantize.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
    quantize_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $quantize.FullName).Hash.ToLowerInvariant()
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 -LiteralPath $buildManifest
Write-Host "llama.cpp pinned and built."
Write-Host "Server: $($server.FullName)"
Write-Host "Quantizer: $($quantize.FullName)"
Write-Host "Build manifest: $buildManifest"
