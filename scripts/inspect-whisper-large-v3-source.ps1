$ErrorActionPreference = "Stop"
$shared = Join-Path $PSScriptRoot "inspect-whisper-large-v3-turbo-source.ps1"
& $shared `
    -Repository "https://huggingface.co/openai/whisper-large-v3" `
    -Revision "06f233fe06e710322aca913c1bc4249a0d71fce1" `
    -CandidateName "openai-whisper-large-v3"
