param(
    [int]$Threads = 4,
    [int]$BeamSize = 5,
    [double]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "benchmark-whisper-large-v3-turbo.ps1") `
    -Language ta `
    -AudioProfile normalized `
    -Threads $Threads `
    -BeamSize $BeamSize `
    -TimeoutSeconds $TimeoutSeconds `
    -CandidateName "openai-whisper-large-v3" `
    -RevisionShort "06f233fe" `
    -EngineLabel "whisper-large-v3"
