param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipConversion
)

$ErrorActionPreference = "Stop"
$arguments = @{
    Revision = "06f233fe06e710322aca913c1bc4249a0d71fce1"
    RepositoryId = "openai/whisper-large-v3"
    CandidateName = "openai-whisper-large-v3"
    ExpectedLicense = "apache-2.0"
    MinimumFreeGB = 15
}
if ($SkipDependencyInstall) { $arguments.SkipDependencyInstall = $true }
if ($SkipConversion) { $arguments.SkipConversion = $true }
& (Join-Path $PSScriptRoot "acquire-whisper-large-v3-turbo.ps1") @arguments
