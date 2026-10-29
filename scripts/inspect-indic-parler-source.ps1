$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot

& (Join-Path $scriptRoot "inspect-expressive-tts-candidates.ps1")
if ($LASTEXITCODE -ne 0) { throw "Parler-TTS code-source inspection failed." }

& (Join-Path $scriptRoot "inspect-indicf5-model-source.ps1") `
    -Repository "https://huggingface.co/ai4bharat/indic-parler-tts" `
    -CandidateName "ai4bharat-indic-parler-tts-model"
if ($LASTEXITCODE -ne 0) { throw "Indic Parler-TTS model-source inspection failed." }
