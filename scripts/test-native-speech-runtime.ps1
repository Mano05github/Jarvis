$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot "native\Jarvis.SpeechRuntime"
$buildRoot = Join-Path $projectRoot "storage\build\native\Jarvis.SpeechRuntime"
$onnxRuntimeRoot = Join-Path $projectRoot "storage\engines\stt\onnxruntime\1.31.1"
$onnxFixture = Join-Path $projectRoot "storage\models\stt\fixtures\tiny-affine-relu-v1\model.onnx"
$cmake = Get-Command cmake.exe -ErrorAction Stop

if (-not (Test-Path -LiteralPath $onnxRuntimeRoot -PathType Container)) {
    throw "Pinned ONNX Runtime is missing. Run scripts\acquire-onnxruntime-fixture.ps1 first."
}
if (-not (Test-Path -LiteralPath $onnxFixture -PathType Leaf)) {
    throw "Verified tiny ONNX fixture is missing. Run tools\generate_tiny_onnx_fixture.py first."
}

New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
& $cmake.Source -S $sourceRoot -B $buildRoot `
    "-DJARVIS_ONNXRUNTIME_ROOT=$onnxRuntimeRoot" `
    "-DJARVIS_ONNX_FIXTURE_MODEL=$onnxFixture"
if ($LASTEXITCODE -ne 0) { throw "Native speech runtime configuration failed." }
& $cmake.Source --build $buildRoot --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw "Native speech runtime build failed." }
& $cmake.Source --build $buildRoot --config Release --target RUN_TESTS
if ($LASTEXITCODE -ne 0) { throw "Native speech runtime contract tests failed." }

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$worker = Join-Path $buildRoot "Release\jarvis_speech_fake_worker.exe"
$processTest = Join-Path $projectRoot "scripts\test-native-speech-worker.py"
& $python $processTest $worker
if ($LASTEXITCODE -ne 0) { throw "Native speech worker process contract failed." }

$governedTest = Join-Path $projectRoot "scripts\test-governed-native-speech.py"
& $python $governedTest $worker
if ($LASTEXITCODE -ne 0) { throw "Governed native speech certification failed." }
