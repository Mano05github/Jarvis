# Personal corpus recording guide

- Record only with explicit owner consent.
- Use mono PCM WAV, 16 kHz, 16-bit where possible.
- Keep one utterance per file with approximately 300 ms of leading/trailing room sound.
- Build 120 utterances: 40 Tamil, 40 English and 40 code-switched.
- Include application names, files, dates, numbers, media controls, questions and technical vocabulary.
- Allocate quiet-near, normal-room and controlled-noise conditions.
- Keep at least 24 utterances held out.
- Do not record passwords, financial data, private messages or other people without consent.
- Store recordings only under `storage/datasets/speech/raw`.

## Native recording command

From `D:\Projects\Jarvis`:

```powershell
.\.venv\Scripts\python.exe -m jarvis corpus-record `
  --manifest storage\datasets\speech\corpus-v1.jsonl `
  --corpus-root storage\datasets\speech `
  --limit 5
```

The command uses the Windows default recording device. Press Enter once to start and again to stop. Use `s` to skip, `q` to end the session, and `c` to cancel an active take. After the five-prompt microphone check, omit `--limit 5` to continue. Existing WAV files are skipped, making sessions safely resumable.

After every take, the recorder reports speech-active RMS, overall RMS and peak level. Short phrases can have a high crest factor, so the warning now requires both very low active energy and a peak below -20 dBFS. Peaks around -18 to -6 dBFS are healthy; avoid peaks above -3 dBFS.

Record `quiet-near` prompts close to the microphone in a quiet room, `normal-room` prompts from a normal seated position, and `controlled-noise` prompts with repeatable low-level background sound. Do not change reference text after recording without re-recording that utterance.

