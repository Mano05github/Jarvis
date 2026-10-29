$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$storageRoot = Join-Path $projectRoot "storage"
$taskAppData = Join-Path $storageRoot "dotnet-appdata"
$taskPackages = Join-Path $storageRoot "cache\nuget\packages"
$nugetConfig = Join-Path $projectRoot "NuGet.Config"
$testProject = Join-Path $projectRoot `
    "native\Jarvis.WindowsBroker.ContractTests\Jarvis.WindowsBroker.ContractTests.csproj"

New-Item -ItemType Directory -Force -Path $taskAppData,$taskPackages | Out-Null
$env:DOTNET_CLI_HOME = $storageRoot
$env:APPDATA = $taskAppData
$env:NUGET_PACKAGES = $taskPackages
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
$env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"

& dotnet build $testProject --configuration Release --nologo --configfile $nugetConfig
if ($LASTEXITCODE -ne 0) { throw "Windows broker build failed." }

& dotnet run --project $testProject --configuration Release --no-build
if ($LASTEXITCODE -ne 0) { throw "Windows broker contract tests failed." }
