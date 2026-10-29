import importlib
import json
import wave
from pathlib import Path
from types import SimpleNamespace

from jarvis.benchmarking.corpus import CorpusEntry, write_corpus
from jarvis.benchmarking.dialogue import write_dialogue_speech, write_dialogues
from jarvis.benchmarking.dialogue_pack import (
    build_phase1_dialogue_speech,
    build_phase1_dialogues,
)
from jarvis.benchmarking.dialogue_session import RecordingSession, SessionRecording
from jarvis.cli import main


def test_doctor_reports_python_and_storage(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["python"]["version"].startswith("3.12")
    assert report["storage"]["root"] == str(storage)


def test_schema_export_writes_registered_contracts(tmp_path) -> None:
    output = tmp_path / "schemas"
    assert main(["schemas-export", "--output", str(output)]) == 0
    assert (output / "Task.json").is_file()
    assert (output / "ActionIntent.json").is_file()
    assert (output / "TranscriptEvidence.json").is_file()
    assert (output / "SemanticPacket.json").is_file()
    assert (output / "IntentEnvelope.json").is_file()
    assert (output / "InteractionEnvelope.json").is_file()
    assert (output / "PlanProposal.json").is_file()


def test_llm_config_commands_never_display_credential_reference(tmp_path, capsys) -> None:
    config = tmp_path / "providers.toml"
    config.write_text(
        """schema_version = "1.0"
default_profile = "azure"

[routing]
companion = "azure"
planner = "azure"

[profiles.azure]
provider = "azure_openai"
endpoint = "https://fixture.openai.azure.com"
deployment = "primary"
api_version = "configured-by-owner"
credential_ref = "secret-reference-that-must-not-print"
remote = true
""",
        encoding="utf-8",
    )

    assert main(["llm-config-validate", "--config", str(config)]) == 0
    validate_output = capsys.readouterr().out
    assert "secret-reference-that-must-not-print" not in validate_output
    assert json.loads(validate_output)["valid"] is True

    assert main(["llm-provider-list", "--config", str(config)]) == 0
    list_output = capsys.readouterr().out
    assert "secret-reference-that-must-not-print" not in list_output
    assert json.loads(list_output)["profiles"]["azure"]["credential_reference_present"] is True


def test_llm_secret_commands_use_store_without_echoing_secret(
    monkeypatch, tmp_path, capsys
) -> None:
    storage = tmp_path / "storage"
    captured: dict[str, str] = {}

    class FakeSecretStore:
        def __init__(self, root: Path) -> None:
            assert root == (storage / "secrets" / "llm").resolve()

        def put(self, reference: str, secret: str) -> None:
            captured[reference] = secret

        def contains(self, reference: str) -> bool:
            return reference in captured

        def get(self, reference: str) -> str | None:
            return captured.get(reference)

    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "DPAPISecretStore", FakeSecretStore)
    monkeypatch.setattr(cli_module.getpass, "getpass", lambda _prompt: "super-secret")

    assert main(["llm-secret-set", "--reference", "azure-primary"]) == 0
    output = capsys.readouterr().out
    assert "super-secret" not in output
    assert json.loads(output) == {"configured": True, "reference": "azure-primary"}

    assert main(["llm-secret-status", "--reference", "azure-primary"]) == 0
    assert json.loads(capsys.readouterr().out)["configured"] is True


def test_text_session_is_explicitly_simulation_only(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    config = tmp_path / "providers.toml"
    config.write_text(
        """schema_version = "1.0"
default_profile = "fixture"
[profiles.fixture]
provider = "fake"
model = "fixture"
remote = false
""",
        encoding="utf-8",
    )
    cli_module = importlib.import_module("jarvis.cli.main")

    class FakeSession:
        def __init__(self, **kwargs) -> None:
            self.audit = kwargs["audit"]
            self.audit.record_session_started()

        def process(self, _text: str):
            return SimpleNamespace(
                reply="Vanakkam.",
                plan_rejection=None,
                simulations=(),
            )

        def snapshot(self):
            return {"execution_mode": "simulation_only"}

        def close(self, reason: str) -> None:
            self.audit.record_session_closed(reason)

    entered = iter(["hello", "/state", "/quit"])
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(entered))
    monkeypatch.setattr(cli_module, "build_providers", lambda *_args: {})
    monkeypatch.setattr(cli_module, "LLMGateway", lambda *_args: object())
    monkeypatch.setattr(cli_module, "ConversationSession", FakeSession)

    assert main(["text-session", "--config", str(config)]) == 0
    output = capsys.readouterr().out
    assert "simulation only" in output
    assert "Jarvis> Vanakkam." in output
    assert '"execution_mode": "simulation_only"' in output
    audit_files = list((storage / "audit" / "sessions").glob("*.jsonl"))
    assert len(audit_files) == 1
    assert "hello" not in audit_files[0].read_text(encoding="utf-8")


def test_storage_init(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    assert main(["storage-init"]) == 0
    assert str(storage) in capsys.readouterr().out
    assert (storage / "engines").is_dir()


def test_corpus_validate(tmp_path, capsys) -> None:
    manifest = tmp_path / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="sample_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/sample.wav",
                consented=True,
            )
        ],
        manifest,
    )
    assert main(["corpus-validate", str(manifest)]) == 0
    assert json.loads(capsys.readouterr().out)["utterances"] == 1


def test_corpus_create_builds_balanced_manifest(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    output = storage / "datasets" / "speech" / "corpus-v1.jsonl"
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))

    assert main(["corpus-create", "--output", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["utterances"] == 120
    assert report["by_language"] == {"en": 40, "mixed": 40, "ta": 40}
    assert len(output.read_text(encoding="utf-8").splitlines()) == 120


def test_dialogue_corpus_create_builds_scenarios_and_speech(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    root = storage / "datasets" / "speech"
    dialogue = root / "dialogue-scenarios-v1.jsonl"
    speech = root / "tanglish-owner-v2.jsonl"
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))

    assert (
        main(
            [
                "dialogue-corpus-create",
                "--output",
                str(dialogue),
                "--speech-output",
                str(speech),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["dialogue"]["scenarios"] == 10
    assert report["speech"]["utterances"] == 40
    assert len(dialogue.read_text(encoding="utf-8").splitlines()) == 10
    assert len(speech.read_text(encoding="utf-8").splitlines()) == 40


def test_dialogue_consolidation_and_semantic_cli_pipeline(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    root = storage / "datasets" / "speech"
    manifest = root / "tanglish-owner-v2.jsonl"
    dialogues = root / "dialogue-scenarios-v1.jsonl"
    sessions = root / "recording-sessions"
    evaluation = root / "evaluation" / "pilot.eval.jsonl"
    stt_manifest = root / "evaluation" / "pilot.stt.jsonl"
    audio = root / "raw" / "mixed-v2" / "tg_001.wav"
    prompt = build_phase1_dialogue_speech()[0]
    write_dialogue_speech([prompt], manifest)
    write_dialogues(build_phase1_dialogues(), dialogues)
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x10\x00" * 3_200)
    session = RecordingSession(
        schema_version="1.0",
        selected=1,
        recorded=1,
        skipped=0,
        stopped_early=False,
        recordings=(
            SessionRecording(
                path=prompt.audio_file,
                duration_seconds=0.2,
                sample_rate_hz=16_000,
                channels=1,
                sample_width_bytes=2,
                frames=3_200,
                rms_dbfs=-30.0,
                active_rms_dbfs=-28.0,
                peak_dbfs=-12.0,
                scenario_id=prompt.scenario_id,
                turn_id=prompt.turn_id,
                spoken_reference="jarvis notepad-ah open pannu",
            ),
        ),
    )
    sessions.mkdir(parents=True)
    (sessions / "pilot.json").write_text(session.model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))

    assert (
        main(
            [
                "dialogue-session-consolidate",
                "--manifest",
                str(manifest),
                "--dialogues",
                str(dialogues),
                "--sessions",
                str(sessions),
                "--corpus-root",
                str(root),
                "--output",
                str(evaluation),
                "--stt-output",
                str(stt_manifest),
            ]
        )
        == 0
    )
    consolidate_report = json.loads(capsys.readouterr().out)
    assert consolidate_report["consolidated"] == 1
    assert evaluation.is_file()
    assert stt_manifest.is_file()

    semantic_output = storage / "benchmarks" / "results" / "semantic-pilot"
    assert (
        main(
            [
                "dialogue-semantic-evaluate",
                "--evaluation",
                str(evaluation),
                "--dialogues",
                str(dialogues),
                "--output-dir",
                str(semantic_output),
            ]
        )
        == 0
    )
    semantic_report = json.loads(capsys.readouterr().out)
    assert semantic_report["strict_semantic_accuracy"] == 1.0
    assert (semantic_output / "semantic-results.jsonl").is_file()
    assert (semantic_output / "summary.json").is_file()
    assert (semantic_output / "report.md").is_file()


def test_corpus_record_dispatches_native_recorder(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    root = storage / "datasets" / "speech"
    manifest = root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="en_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/en/en_001.wav",
                consented=True,
            )
        ],
        manifest,
    )
    expected = {"schema_version": "1.0", "selected": 1, "recorded": 0}
    cli_module = importlib.import_module("jarvis.cli.main")
    recorder = object()
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "MciWaveRecorder", lambda: recorder)
    monkeypatch.setattr(
        cli_module,
        "record_corpus_interactive",
        lambda entries, corpus_root, received, **_kwargs: expected,
    )

    assert (
        main(
            [
                "corpus-record",
                "--manifest",
                str(manifest),
                "--corpus-root",
                str(root),
                "--limit",
                "1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected


def test_corpus_normalize_writes_derived_manifest(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    root = storage / "datasets" / "speech"
    audio = root / "raw" / "en" / "en_001.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x10\x00\xf0\xff" * 1_600)
    manifest = root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="en_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/en/en_001.wav",
                consented=True,
            )
        ],
        manifest,
    )
    derived = root / "corpus-normalized.jsonl"
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))

    assert (
        main(
            [
                "corpus-normalize",
                "--manifest",
                str(manifest),
                "--corpus-root",
                str(root),
                "--output-manifest",
                str(derived),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["processed"] == 1
    assert report["clipped_samples"] == 0
    assert derived.is_file()
    assert (root / "processed" / "normalized-v1" / "en" / "en_001.wav").is_file()


def test_stt_whisper_smoke_writes_private_summary(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    executable = storage / "engines" / "stt" / "whisper.exe"
    model = storage / "models" / "stt" / "model.bin"
    audio = storage / "datasets" / "speech" / "sample.wav"
    for path in (executable, model, audio):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    expected = {
        "schema_version": "1.0",
        "status": "passed",
        "transcript_characters": 12,
        "transcript_sha256": "0" * 64,
    }
    captured: dict[str, Path] = {}

    def fake_smoke(_adapter, requested_audio: Path, output: Path):
        assert requested_audio == audio
        captured["output"] = output
        return expected

    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setattr(cli_module, "smoke_stt", fake_smoke)
    assert (
        main(
            [
                "stt-whisper-smoke",
                "--audio",
                str(audio),
                "--executable",
                str(executable),
                "--model",
                str(model),
                "--engine-id",
                "fixture",
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out) == expected
    assert json.loads((captured["output"] / "summary.json").read_text()) == expected


def test_stt_whisper_server_benchmark_dispatches_resident_adapter(
    monkeypatch, tmp_path, capsys
) -> None:
    storage = tmp_path / "storage"
    executable = storage / "engines" / "stt" / "whisper-server.exe"
    model = storage / "models" / "stt" / "model.bin"
    root = storage / "datasets" / "speech"
    manifest = root / "corpus.jsonl"
    executable.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    executable.touch()
    model.touch()
    write_corpus(
        [
            CorpusEntry(
                utterance_id="en_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/en/en_001.wav",
                consented=True,
            )
        ],
        manifest,
    )
    expected = {
        "schema_version": "1.0",
        "engine_id": "resident-fixture",
        "completed": 1,
    }

    class FakeServer:
        startup_seconds = 1.25

        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def memory_evidence(self):
            return {"profile_name": "faster-whisper", "certification_mode": True}

    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "WhisperServerAdapter", FakeServer)
    monkeypatch.setattr(cli_module, "benchmark_stt", lambda **_kwargs: expected)

    assert (
        main(
            [
                "stt-whisper-server-benchmark",
                "--corpus",
                str(manifest),
                "--corpus-root",
                str(root),
                "--executable",
                str(executable),
                "--model",
                str(model),
                "--engine-id",
                "resident-fixture",
                "--language",
                "en",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected


def test_faster_whisper_benchmark_dispatches_isolated_worker(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    python = storage / "engines" / "stt" / "runtime" / "Scripts" / "python.exe"
    model = storage / "models" / "stt" / "ctranslate2" / "model"
    root = storage / "datasets" / "speech"
    manifest = root / "corpus.jsonl"
    python.parent.mkdir(parents=True)
    model.mkdir(parents=True)
    python.touch()
    write_corpus(
        [
            CorpusEntry(
                utterance_id="tg_001",
                language="mixed",
                reference="notepad open pannu",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/mixed-v2/tg_001.wav",
                consented=True,
            )
        ],
        manifest,
    )
    expected = {
        "schema_version": "1.0",
        "engine_id": "tamil-worker-fixture",
        "completed": 1,
    }

    class FakeWorker:
        startup_seconds = 2.5

        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def memory_evidence(self):
            return {"profile_name": "faster-whisper", "certification_mode": True}

    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "FasterWhisperWorkerAdapter", FakeWorker)
    monkeypatch.setattr(cli_module, "benchmark_stt", lambda **_kwargs: expected)
    worker = Path(__file__).resolve().parents[2] / "tools" / "faster_whisper_worker.py"

    assert (
        main(
            [
                "stt-faster-whisper-benchmark",
                "--corpus",
                str(manifest),
                "--corpus-root",
                str(root),
                "--python",
                str(python),
                "--worker",
                str(worker),
                "--model-dir",
                str(model),
                "--engine-id",
                "tamil-worker-fixture",
                "--corpus-language",
                "mixed",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected


def test_faster_whisper_benchmark_reports_memory_denial(monkeypatch, tmp_path, capsys) -> None:
    from jarvis.runtime.memory import MemoryAdmissionDecision, MemoryAdmissionError

    storage = tmp_path / "storage"
    python = storage / "engines" / "stt" / "runtime" / "Scripts" / "python.exe"
    model = storage / "models" / "stt" / "ctranslate2" / "model"
    corpus_root = storage / "datasets" / "speech"
    manifest = corpus_root / "corpus.jsonl"
    python.parent.mkdir(parents=True)
    model.mkdir(parents=True)
    python.touch()
    write_corpus([], manifest)

    class DeniedWorker:
        def __init__(self, _config, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise MemoryAdmissionError(
                MemoryAdmissionDecision(
                    allowed=False,
                    worker_name="faster-whisper",
                    reason="insufficient_physical_headroom",
                    pressure="soft_pressure",
                    requested_bytes=3,
                    unrealized_reserved_bytes=0,
                    physical_headroom_bytes=1,
                    commit_headroom_bytes=10,
                )
            )

        def __exit__(self, *_args) -> None:
            return None

    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "FasterWhisperWorkerAdapter", DeniedWorker)
    worker = Path(__file__).resolve().parents[2] / "tools" / "faster_whisper_worker.py"

    result = main(
        [
            "stt-faster-whisper-benchmark",
            "--corpus",
            str(manifest),
            "--corpus-root",
            str(corpus_root),
            "--python",
            str(python),
            "--worker",
            str(worker),
            "--model-dir",
            str(model),
            "--engine-id",
            "denied-fixture",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 3
    assert output["error_code"] == "memory_admission_denied"
    assert output["decision"]["reason"] == "insufficient_physical_headroom"


def test_mms_vits_benchmark_dispatches_isolated_worker(monkeypatch, tmp_path, capsys) -> None:
    storage = tmp_path / "storage"
    python = storage / "engines" / "tts" / "runtime" / "Scripts" / "python.exe"
    model = storage / "models" / "tts" / "mms-tamil"
    manifest = storage / "datasets" / "speech" / "tts.jsonl"
    python.parent.mkdir(parents=True)
    model.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    python.touch()
    manifest.write_text(
        '{"schema_version":"1.0","utterance_id":"ta_001","language":"ta",'
        '"text":"வணக்கம்","category":"conversation","split":"development"}\n',
        encoding="utf-8",
    )
    expected = {"schema_version": "1.0", "engine_id": "mms-fixture", "completed": 1}

    class FakeWorker:
        startup_seconds = 1.5

        def __init__(self, config) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    cli_module = importlib.import_module("jarvis.cli.main")
    monkeypatch.setenv("JARVIS_STORAGE_ROOT", str(storage))
    monkeypatch.setattr(cli_module, "MmsVitsWorkerAdapter", FakeWorker)
    monkeypatch.setattr(cli_module, "benchmark_tts", lambda **_kwargs: expected)
    worker = Path(__file__).resolve().parents[2] / "tools" / "mms_vits_worker.py"

    assert (
        main(
            [
                "tts-mms-vits-benchmark",
                "--manifest",
                str(manifest),
                "--python",
                str(python),
                "--worker",
                str(worker),
                "--model-dir",
                str(model),
                "--engine-id",
                "mms-fixture",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected
