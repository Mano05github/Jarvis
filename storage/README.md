# Jarvis local storage

This directory is the canonical root for large, machine-local Jarvis files. Model downloads, datasets, caches, benchmark recordings, logs, and generated artifacts must remain under this directory rather than the user profile or system drive.

## Layout

- `models/stt`: Whisper and other speech-to-text models
- `models/tts`: speech synthesis models and approved voice assets
- `models/vad`: voice-activity-detection models
- `models/wakeword`: local wake-word models
- `models/llm`: optional small local language models
- `engines`: compiled/runtime binaries for STT, TTS, VAD and wake-word engines
- `datasets/speech`: raw, transcribed, and processed benchmark utterances
- `benchmarks`: results, logs, and generated artifacts
- `audit/sessions`: metadata-only, hash-chained session event logs; no prompt or reply bodies
- `cache`: Hugging Face, PyTorch, pip, and uv caches
- `temp`: project-scoped temporary files
- `secrets`: Windows user-bound DPAPI credential blobs; references only appear in configuration

The contents are intentionally ignored by Git, except for this file. Raw voice recordings and transcripts may contain personal information; they are local-only and should not be uploaded or committed.

