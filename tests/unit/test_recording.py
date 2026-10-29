import wave
from pathlib import Path

import pytest

from jarvis.benchmarking import recording
from jarvis.benchmarking.corpus import CorpusEntry
from jarvis.benchmarking.dialogue import DialogueSpeechEntry
from jarvis.benchmarking.recording import (
    MciWaveRecorder,
    record_corpus_interactive,
    validate_recording,
)


class FakeRecorder:
    def __init__(self) -> None:
        self.active = False
        self.cancelled = 0

    def start(self) -> None:
        self.active = True

    def stop_and_save(self, output: Path) -> None:
        assert self.active
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\x00\x00" * 3_200)
        self.active = False

    def cancel(self) -> None:
        self.cancelled += 1
        self.active = False


def entry(identifier: str = "en_001") -> CorpusEntry:
    return CorpusEntry(
        utterance_id=identifier,
        language="en",
        reference="Open Notepad",
        intent_label="app.open",
        condition="quiet-near",
        split="development",
        audio_file=f"raw/en/{identifier}.wav",
        consented=True,
    )


def test_record_corpus_interactive_saves_validated_wav(tmp_path: Path) -> None:
    answers = iter(["", ""])
    recorder = FakeRecorder()
    messages: list[str] = []
    summary = record_corpus_interactive(
        [entry()],
        tmp_path,
        recorder,
        input_fn=lambda _prompt: next(answers),
        output_fn=messages.append,
    )

    target = tmp_path / "raw" / "en" / "en_001.wav"
    assert target.is_file()
    assert summary["recorded"] == 1
    assert summary["stopped_early"] is False
    assert validate_recording(target).duration_seconds == pytest.approx(0.2)
    assert recorder.cancelled == 1
    assert any("speech level is low" in message for message in messages)


def test_record_corpus_interactive_can_skip_and_quit(tmp_path: Path) -> None:
    answers = iter(["s", "q"])
    summary = record_corpus_interactive(
        [entry("en_001"), entry("en_002")],
        tmp_path,
        FakeRecorder(),
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _message: None,
    )
    assert summary["recorded"] == 0
    assert summary["skipped"] == 1
    assert summary["stopped_early"] is True


def test_record_dialogue_speech_captures_actual_spoken_reference(tmp_path: Path) -> None:
    prompt = DialogueSpeechEntry(
        utterance_id="tg_001",
        reference="Jarvis, notepad-ah open pannu",
        elicitation="Ask Jarvis naturally to open Notepad.",
        intent_label="app.open",
        scenario_id="dlg_001",
        turn_id="dlg_001_t01",
        condition="quiet-near",
        split="development",
        audio_file="raw/mixed-v2/tg_001.wav",
        consented=True,
    )
    answers = iter(["", "", "notepad open pannidu"])
    messages: list[str] = []

    summary = record_corpus_interactive(
        [prompt],
        tmp_path,
        FakeRecorder(),
        input_fn=lambda _prompt: next(answers),
        output_fn=messages.append,
    )

    recording = summary["recordings"][0]
    assert recording["spoken_reference"] == "notepad open pannidu"
    assert recording["scenario_id"] == "dlg_001"
    assert recording["utterance_id"] == "tg_001"
    assert len(recording["audio_sha256"]) == 64
    assert summary["schema_version"] == "2.0"
    assert any("Say it naturally" in message for message in messages)


def test_dialogue_rerecord_archives_previous_take(tmp_path: Path) -> None:
    prompt = DialogueSpeechEntry(
        utterance_id="tg_001",
        reference="Notepad open pannu",
        elicitation="Open Notepad naturally.",
        intent_label="app.open",
        scenario_id="dlg_001",
        turn_id="dlg_001_t01",
        condition="quiet-near",
        split="development",
        audio_file="raw/mixed-v2/tg_001.wav",
        consented=True,
    )
    target = tmp_path / prompt.audio_file
    target.parent.mkdir(parents=True)
    with wave.open(str(target), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x20\x00" * 4_000)
    previous = target.read_bytes()
    answers = iter(["", "", "notepad open pannu"])

    summary = record_corpus_interactive(
        [prompt],
        tmp_path,
        FakeRecorder(),
        overwrite=True,
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _message: None,
    )

    archived = summary["recordings"][0]["archived_previous"]
    assert archived is not None
    assert (tmp_path / archived).read_bytes() == previous
    assert target.read_bytes() != previous


def test_validate_recording_rejects_wrong_format(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\x00\x00" * 4_410)
    with pytest.raises(ValueError, match="mono 16-bit PCM"):
        validate_recording(path)


class FakeMciFunction:
    def __init__(self, error_command: str | None = None) -> None:
        self.error_command = error_command
        self.commands: list[str] = []

    def __call__(self, command, _response, _length, _callback):
        self.commands.append(command)
        return 5 if self.error_command and command.startswith(self.error_command) else 0


class FakeErrorFunction:
    def __call__(self, _code, message, _length):
        message.value = "simulated MCI failure"
        return True


class FakeWinmm:
    def __init__(self, error_command: str | None = None) -> None:
        self.mciSendStringW = FakeMciFunction(error_command)
        self.mciGetErrorStringW = FakeErrorFunction()


def test_mci_recorder_issues_bounded_native_commands(monkeypatch, tmp_path: Path) -> None:
    api = FakeWinmm()
    monkeypatch.setattr(recording.ctypes, "WinDLL", lambda _name: api)
    recorder = MciWaveRecorder()

    recorder.start()
    with pytest.raises(RuntimeError, match="already active"):
        recorder.start()
    recorder.stop_and_save(tmp_path / "sample.wav")
    recorder.cancel()

    commands = api.mciSendStringW.commands
    assert commands[0].startswith("open new type waveaudio alias jarvis_")
    assert commands[1].startswith("set jarvis_")
    assert commands[2].startswith("record jarvis_")
    assert commands[3].startswith("stop jarvis_")
    assert commands[4].startswith("save jarvis_")
    assert commands[5].startswith("close jarvis_")


def test_mci_recorder_closes_device_after_native_failure(monkeypatch) -> None:
    api = FakeWinmm(error_command="record")
    monkeypatch.setattr(recording.ctypes, "WinDLL", lambda _name: api)
    recorder = MciWaveRecorder()

    with pytest.raises(OSError, match="simulated MCI failure"):
        recorder.start()
    assert api.mciSendStringW.commands[-1].startswith("close jarvis_")
