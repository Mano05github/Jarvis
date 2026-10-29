param(
    [string]$RunId = "facebook-mms-tts-tam-e9cf59da-20261015T134427Z",
    [ValidateSet("all", "ta", "en", "mixed")]
    [string]$Language = "all",
    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$resultsRoot = Join-Path $projectRoot "storage\benchmarks\results"
$runDirectory = Join-Path $resultsRoot $RunId
$artifactRoot = Join-Path $runDirectory "artifacts"
$manifest = Join-Path $projectRoot "benchmarks\speech\tts-eval-v1.jsonl"
$reviewRoot = Join-Path $projectRoot "storage\benchmarks\reviews"
$output = Join-Path $reviewRoot "$RunId-owner-review.jsonl"

$resolvedResultsRoot = (Resolve-Path -LiteralPath $resultsRoot).Path
$resolvedRunDirectory = (Resolve-Path -LiteralPath $runDirectory).Path
if (-not $resolvedRunDirectory.StartsWith($resolvedResultsRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "Review run must stay under $resolvedResultsRoot"
}
if (-not (Test-Path -LiteralPath $artifactRoot -PathType Container)) {
    throw "Benchmark artifact directory is missing: $artifactRoot"
}
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "TTS manifest is missing: $manifest"
}
New-Item -ItemType Directory -Force -Path $reviewRoot | Out-Null

function Read-Rating {
    param([string]$Label)
    while ($true) {
        $raw = Read-Host "$Label (1=poor, 5=excellent)"
        [int]$value = 0
        if ([int]::TryParse($raw, [ref]$value) -and $value -ge 1 -and $value -le 5) {
            return $value
        }
        Write-Host "Enter one whole number from 1 to 5." -ForegroundColor Yellow
    }
}

function Read-YesNo {
    param([string]$Label)
    while ($true) {
        $raw = (Read-Host "$Label (y/n)").Trim().ToLowerInvariant()
        if ($raw -eq "y" -or $raw -eq "yes") { return $true }
        if ($raw -eq "n" -or $raw -eq "no") { return $false }
        Write-Host "Enter y or n." -ForegroundColor Yellow
    }
}

$entries = @(Get-Content -LiteralPath $manifest -Encoding utf8 | ForEach-Object {
    $_ | ConvertFrom-Json
} | Where-Object {
    $_.split -eq "development" -and ($Language -eq "all" -or $_.language -eq $Language)
})
$reviewed = @{}
if (Test-Path -LiteralPath $output) {
    Get-Content -LiteralPath $output -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object {
        $record = $_ | ConvertFrom-Json
        $reviewed[[string]$record.utterance_id] = $true
    }
}

Write-Host "MMS Tamil development listening review"
Write-Host "Run: $RunId"
Write-Host "Scores are stored locally at: $output"
Write-Host "Held-out prompts are excluded. Previously scored samples are skipped."

if ($ListOnly) {
    foreach ($entry in $entries) {
        $utteranceId = [string]$entry.utterance_id
        $audio = Join-Path $artifactRoot "$utteranceId\$utteranceId.wav"
        if (-not (Test-Path -LiteralPath $audio -PathType Leaf)) {
            throw "Development audio is missing: $audio"
        }
        Write-Host "$utteranceId`t$($entry.language)`t$audio"
    }
    Write-Host "Validated $($entries.Count) development review samples."
    exit 0
}

foreach ($entry in $entries) {
    $utteranceId = [string]$entry.utterance_id
    if ($reviewed.ContainsKey($utteranceId)) { continue }
    $audio = Join-Path $artifactRoot "$utteranceId\$utteranceId.wav"
    if (-not (Test-Path -LiteralPath $audio -PathType Leaf)) {
        throw "Development audio is missing: $audio"
    }

    Write-Host ""
    Write-Host "[$utteranceId] language=$($entry.language)" -ForegroundColor Cyan
    Write-Host $entry.text
    while ($true) {
        $player = [System.Media.SoundPlayer]::new($audio)
        try {
            $player.Load()
            $player.PlaySync()
        } finally {
            $player.Dispose()
        }
        $action = (Read-Host "Press Enter to score, r to replay, or q to save and quit").Trim().ToLowerInvariant()
        if ($action -eq "r") { continue }
        if ($action -eq "q") { break }

        $record = [ordered]@{
            schema_version = "1.0"
            run_id = $RunId
            engine_id = "facebook-mms-tts-tam-e9cf59da"
            utterance_id = $utteranceId
            language = [string]$entry.language
            split = "development"
            audio_sha256 = (Get-FileHash -LiteralPath $audio -Algorithm SHA256).Hash.ToLowerInvariant()
            intelligibility = Read-Rating "Intelligibility"
            pronunciation = Read-Rating "Pronunciation accuracy"
            naturalness = Read-Rating "Naturalness and pacing"
            jarvis_voice_fit = Read-Rating "Warm, confident Jarvis voice fit"
            identity_distinct = Read-YesNo "Does it sound original rather than like a known public figure?"
            acceptable = Read-YesNo "Accept this sample for the candidate?"
            notes = (Read-Host "Optional short notes").Trim()
            reviewed_at = [DateTimeOffset]::UtcNow.ToString("o")
        }
        $json = $record | ConvertTo-Json -Compress
        [IO.File]::AppendAllText(
            $output,
            $json + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false)
        )
        $reviewed[$utteranceId] = $true
        break
    }
    if ($action -eq "q") { break }
}

$completed = 0
if (Test-Path -LiteralPath $output) {
    $completed = @(Get-Content -LiteralPath $output -Encoding utf8 | Where-Object { $_.Trim() }).Count
}
Write-Host ""
Write-Host "Review progress: $completed / $($entries.Count) development samples"
Write-Host "Review file: $output"
