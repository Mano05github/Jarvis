"""Command-line entry points for Phase 1 foundation tooling."""

from __future__ import annotations

import argparse
import getpass
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from jarvis.benchmarking.audio import normalize_corpus
from jarvis.benchmarking.corpus import load_corpus, summarize_corpus, write_corpus
from jarvis.benchmarking.deterministic_semantic import (
    benchmark_deterministic_semantics,
)
from jarvis.benchmarking.dialogue import (
    DialogueScenario,
    DialogueSpeechEntry,
    DialogueTurn,
    load_dialogue_speech,
    load_dialogues,
    summarize_dialogue_speech,
    summarize_dialogues,
    write_dialogue_speech,
    write_dialogues,
)
from jarvis.benchmarking.dialogue_pack import (
    build_phase1_dialogue_speech,
    build_phase1_dialogues,
)
from jarvis.benchmarking.dialogue_session import (
    DialogueEvaluationEntry,
    RecordingSession,
    SessionRecording,
    consolidate_dialogue_sessions,
    load_evaluation_manifest,
    sha256_file,
    write_evaluation_manifest,
)
from jarvis.benchmarking.espeak_ng import EspeakAdapter, EspeakConfig
from jarvis.benchmarking.faster_whisper_worker import (
    FasterWhisperWorkerAdapter,
    FasterWhisperWorkerConfig,
)
from jarvis.benchmarking.mms_vits_worker import (
    MmsVitsWorkerAdapter,
    MmsVitsWorkerConfig,
)
from jarvis.benchmarking.process import ExecutionLimits
from jarvis.benchmarking.prompt_pack import build_phase1_corpus
from jarvis.benchmarking.qwen_semantic import (
    QwenServerAdapter,
    QwenServerConfig,
    benchmark_qwen_core,
    benchmark_qwen_semantics,
    load_decoder_cases,
)
from jarvis.benchmarking.recording import MciWaveRecorder, record_corpus_interactive
from jarvis.benchmarking.smoke import smoke_stt
from jarvis.benchmarking.stt import benchmark_stt
from jarvis.benchmarking.tanglish_semantics import (
    DialogueState,
    SemanticInterpretation,
    SemanticSampleResult,
    evaluate_semantics,
    load_transcripts,
    write_semantic_report,
)
from jarvis.benchmarking.tts import benchmark_tts
from jarvis.benchmarking.whisper_cpp import WhisperCppAdapter, WhisperCppConfig
from jarvis.benchmarking.whisper_server import (
    WhisperServerAdapter,
    WhisperServerConfig,
)
from jarvis.contracts import CONTRACT_TYPES
from jarvis.llm import (
    DPAPISecretStore,
    LLMGateway,
    ProviderError,
    build_providers,
    load_gateway_config,
    redacted_gateway_config,
)
from jarvis.llm.evaluation import (
    evaluate_companion_gateway,
    load_companion_cases,
    select_companion_cases,
)
from jarvis.models import load_manifest, verify_model
from jarvis.runtime import (
    ConversationSession,
    JsonlSessionAuditLog,
    MemoryAdmissionError,
    MemoryGovernor,
    load_memory_runtime_config,
)
from jarvis.storage import StorageLayout
from jarvis.telemetry import system_inventory


def _write_json(value: object, output: Path | None = None) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    if output is None:
        print(payload, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis Phase 1 tooling")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="print privacy-safe environment diagnostics")
    subcommands.add_parser("storage-init", help="create the canonical storage layout")

    schemas = subcommands.add_parser("schemas-export", help="export versioned JSON Schemas")
    schemas.add_argument("--output", type=Path, default=Path("artifacts/schemas"))

    llm_validate = subcommands.add_parser(
        "llm-config-validate", help="validate and safely summarize an LLM provider config"
    )
    llm_validate.add_argument("--config", type=Path, required=True)

    llm_list = subcommands.add_parser(
        "llm-provider-list", help="list configured providers without exposing credentials"
    )
    llm_list.add_argument("--config", type=Path, required=True)

    llm_secret_set = subcommands.add_parser(
        "llm-secret-set", help="securely prompt for and store a provider credential"
    )
    llm_secret_set.add_argument("--reference", required=True)

    llm_secret_status = subcommands.add_parser(
        "llm-secret-status", help="report whether a credential reference is configured"
    )
    llm_secret_status.add_argument("--reference", required=True)

    llm_evaluate = subcommands.add_parser(
        "llm-companion-evaluate",
        help="run a controlled text-only companion/planner provider evaluation",
    )
    llm_evaluate.add_argument("--config", type=Path, required=True)
    llm_evaluate.add_argument("--cases", type=Path, required=True)
    llm_evaluate.add_argument("--rubric", type=Path, required=True)
    llm_evaluate.add_argument("--limit", type=int, default=None)
    llm_evaluate.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="run one named case; repeat to run multiple cases",
    )

    text_session = subcommands.add_parser(
        "text-session",
        help="run a multi-turn Jarvis text session with simulation-only actions",
    )
    text_session.add_argument("--config", type=Path, required=True)
    text_session.add_argument(
        "--rubric",
        type=Path,
        default=Path("config/llm/companion-planner-rubric-v1.txt"),
    )

    verify = subcommands.add_parser("model-verify", help="verify a model against its manifest")
    verify.add_argument("manifest", type=Path)

    corpus = subcommands.add_parser("corpus-validate", help="validate a speech corpus manifest")
    corpus.add_argument("manifest", type=Path)

    corpus_create = subcommands.add_parser(
        "corpus-create", help="create the balanced Phase 1 speech manifest"
    )
    corpus_create.add_argument("--output", type=Path, required=True)

    corpus_record = subcommands.add_parser(
        "corpus-record", help="record the corpus using the Windows default microphone"
    )
    corpus_record.add_argument("--manifest", type=Path, required=True)
    corpus_record.add_argument("--corpus-root", type=Path, required=True)
    corpus_record.add_argument("--start-at")
    corpus_record.add_argument("--limit", type=int)
    corpus_record.add_argument("--overwrite", action="store_true")

    dialogue_create = subcommands.add_parser(
        "dialogue-corpus-create",
        help="create original Tanglish dialogue scenarios and owner-speech prompts",
    )
    dialogue_create.add_argument("--output", type=Path, required=True)
    dialogue_create.add_argument("--speech-output", type=Path, required=True)

    dialogue_validate = subcommands.add_parser(
        "dialogue-corpus-validate", help="validate a multi-turn dialogue manifest"
    )
    dialogue_validate.add_argument("manifest", type=Path)

    dialogue_speech_validate = subcommands.add_parser(
        "dialogue-speech-validate", help="validate the natural Tanglish speech manifest"
    )
    dialogue_speech_validate.add_argument("manifest", type=Path)

    dialogue_speech_record = subcommands.add_parser(
        "dialogue-speech-record", help="record natural owner Tanglish from scenario prompts"
    )
    dialogue_speech_record.add_argument("--manifest", type=Path, required=True)
    dialogue_speech_record.add_argument("--corpus-root", type=Path, required=True)
    dialogue_speech_record.add_argument("--session-output", type=Path, required=True)
    dialogue_speech_record.add_argument("--start-at")
    dialogue_speech_record.add_argument("--limit", type=int)
    dialogue_speech_record.add_argument("--overwrite", action="store_true")

    dialogue_consolidate = subcommands.add_parser(
        "dialogue-session-consolidate",
        help="bind dialogue sessions to current audio and actual spoken references",
    )
    dialogue_consolidate.add_argument("--manifest", type=Path, required=True)
    dialogue_consolidate.add_argument("--dialogues", type=Path, required=True)
    dialogue_consolidate.add_argument("--sessions", type=Path, required=True)
    dialogue_consolidate.add_argument("--corpus-root", type=Path, required=True)
    dialogue_consolidate.add_argument("--output", type=Path, required=True)
    dialogue_consolidate.add_argument("--stt-output", type=Path, required=True)

    semantic_evaluate = subcommands.add_parser(
        "dialogue-semantic-evaluate",
        help="score Tanglish intent, slots, referents and safety markers",
    )
    semantic_evaluate.add_argument("--evaluation", type=Path, required=True)
    semantic_evaluate.add_argument("--dialogues", type=Path, required=True)
    semantic_evaluate.add_argument("--output-dir", type=Path, required=True)
    semantic_evaluate.add_argument("--transcripts", type=Path)

    corpus_normalize = subcommands.add_parser(
        "corpus-normalize", help="create bounded normalized WAV derivatives"
    )
    corpus_normalize.add_argument("--manifest", type=Path, required=True)
    corpus_normalize.add_argument("--corpus-root", type=Path, required=True)
    corpus_normalize.add_argument("--output-manifest", type=Path, required=True)
    corpus_normalize.add_argument(
        "--output-prefix", type=Path, default=Path("processed/normalized-v1")
    )

    stt = subcommands.add_parser("stt-whisper-benchmark", help="benchmark whisper.cpp")
    stt.add_argument("--corpus", type=Path, required=True)
    stt.add_argument("--corpus-root", type=Path, required=True)
    stt.add_argument("--executable", type=Path, required=True)
    stt.add_argument("--model", type=Path, required=True)
    stt.add_argument("--engine-id", required=True)
    stt.add_argument("--threads", type=int, default=4)
    stt.add_argument("--timeout", type=float, default=120.0)
    stt.add_argument("--language", choices=("auto", "en", "ta"), default="auto")
    stt.add_argument("--corpus-language", choices=("en", "ta", "mixed"))

    stt_server = subcommands.add_parser(
        "stt-whisper-server-benchmark", help="benchmark a resident whisper.cpp server"
    )
    stt_server.add_argument("--corpus", type=Path, required=True)
    stt_server.add_argument("--corpus-root", type=Path, required=True)
    stt_server.add_argument("--executable", type=Path, required=True)
    stt_server.add_argument("--model", type=Path, required=True)
    stt_server.add_argument("--engine-id", required=True)
    stt_server.add_argument("--threads", type=int, default=4)
    stt_server.add_argument("--timeout", type=float, default=120.0)
    stt_server.add_argument("--language", choices=("auto", "en", "ta"), default="auto")
    stt_server.add_argument("--corpus-language", choices=("en", "ta", "mixed"))

    faster_stt = subcommands.add_parser(
        "stt-faster-whisper-benchmark",
        help="benchmark an isolated resident faster-whisper worker",
    )
    faster_stt.add_argument("--corpus", type=Path, required=True)
    faster_stt.add_argument("--corpus-root", type=Path, required=True)
    faster_stt.add_argument("--python", type=Path, required=True)
    faster_stt.add_argument("--worker", type=Path, required=True)
    faster_stt.add_argument("--model-dir", type=Path, required=True)
    faster_stt.add_argument("--engine-id", required=True)
    faster_stt.add_argument("--threads", type=int, default=4)
    faster_stt.add_argument("--timeout", type=float, default=120.0)
    faster_stt.add_argument("--language", choices=("auto", "en", "ta"), default="ta")
    faster_stt.add_argument(
        "--compute-type", choices=("int8", "int8_float32", "float32"), default="int8"
    )
    faster_stt.add_argument("--hotwords")
    faster_stt.add_argument("--beam-size", type=int, default=5)
    faster_stt.add_argument("--word-timestamps", action="store_true")
    faster_stt.add_argument("--corpus-language", choices=("en", "ta", "mixed"))

    qwen = subcommands.add_parser(
        "qwen-semantic-benchmark",
        help="measure Q4_K_M Tanglish semantic quality, RAM, paging and latency",
    )
    qwen.add_argument("--executable", type=Path, required=True)
    qwen.add_argument("--model", type=Path, required=True)
    qwen.add_argument("--cases", type=Path, required=True)
    qwen.add_argument("--rubric", type=Path, required=True)
    qwen.add_argument("--codebooks", type=Path, required=True)
    qwen.add_argument("--grammar", type=Path, required=True)
    qwen.add_argument("--engine-id", default="qwen3-8b-tanglish-q4-k-m")
    qwen.add_argument("--mode", choices=("packet", "core"), default="packet")
    qwen.add_argument("--threads", type=int, default=4)
    qwen.add_argument("--context-size", type=int, default=1024)
    qwen.add_argument("--batch-size", type=int, default=128)
    qwen.add_argument("--micro-batch-size", type=int, default=64)
    qwen.add_argument("--max-output-tokens", type=int, default=48)
    qwen.add_argument("--suite", choices=("oracle", "all"), default="oracle")
    qwen.add_argument("--stability-requests", type=int, default=0)
    qwen.add_argument("--startup-timeout", type=float, default=300.0)
    qwen.add_argument("--request-timeout", type=float, default=120.0)

    deterministic = subcommands.add_parser(
        "deterministic-semantic-benchmark",
        help="certify bounded Tanglish decoding without a resident language model",
    )
    deterministic.add_argument("--cases", type=Path, required=True)
    deterministic.add_argument("--codebooks", type=Path, required=True)
    deterministic.add_argument("--engine-id", default="deterministic-tanglish-v1")
    deterministic.add_argument("--repetitions", type=int, default=100)

    smoke = subcommands.add_parser("stt-whisper-smoke", help="run a private STT smoke test")
    smoke.add_argument("--audio", type=Path, required=True)
    smoke.add_argument("--executable", type=Path, required=True)
    smoke.add_argument("--model", type=Path, required=True)
    smoke.add_argument("--engine-id", required=True)
    smoke.add_argument("--threads", type=int, default=4)
    smoke.add_argument("--timeout", type=float, default=120.0)
    smoke.add_argument("--language", choices=("auto", "en", "ta"), default="auto")

    tts = subcommands.add_parser("tts-espeak-benchmark", help="benchmark eSpeak NG")
    tts.add_argument("--manifest", type=Path, required=True)
    tts.add_argument("--executable", type=Path, required=True)
    tts.add_argument("--engine-id", default="espeak-ng-ta")
    tts.add_argument("--voice", default="ta")
    tts.add_argument("--speed", type=int, default=155)
    tts.add_argument("--timeout", type=float, default=30.0)
    tts.add_argument("--language", choices=("ta", "en", "mixed"))
    tts.add_argument("--split", choices=("development", "held-out"))

    mms_tts = subcommands.add_parser(
        "tts-mms-vits-benchmark",
        help="benchmark an isolated resident Tamil MMS VITS worker",
    )
    mms_tts.add_argument("--manifest", type=Path, required=True)
    mms_tts.add_argument("--python", type=Path, required=True)
    mms_tts.add_argument("--worker", type=Path, required=True)
    mms_tts.add_argument("--model-dir", type=Path, required=True)
    mms_tts.add_argument("--engine-id", default="facebook-mms-tts-tam")
    mms_tts.add_argument("--threads", type=int, default=4)
    mms_tts.add_argument("--seed", type=int, default=7)
    mms_tts.add_argument("--speaking-rate", type=float, default=1.0)
    mms_tts.add_argument("--noise-scale", type=float, default=0.667)
    mms_tts.add_argument("--noise-scale-duration", type=float, default=0.8)
    mms_tts.add_argument("--pronunciation-lexicon", type=Path)
    mms_tts.add_argument("--startup-timeout", type=float, default=180.0)
    mms_tts.add_argument("--timeout", type=float, default=120.0)
    mms_tts.add_argument("--language", choices=("ta", "en", "mixed"))
    mms_tts.add_argument("--split", choices=("development", "held-out"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    layout = StorageLayout.from_environment()

    if args.command == "doctor":
        layout.initialize()
        _write_json(system_inventory(layout))
        return 0
    if args.command == "storage-init":
        layout.initialize()
        print(layout.root)
        return 0
    if args.command == "schemas-export":
        output: Path = args.output
        schema_types: tuple[type[BaseModel], ...] = (
            *CONTRACT_TYPES,
            DialogueTurn,
            DialogueScenario,
            DialogueSpeechEntry,
            SessionRecording,
            RecordingSession,
            DialogueEvaluationEntry,
            DialogueState,
            SemanticInterpretation,
            SemanticSampleResult,
        )
        for contract_type in schema_types:
            target = output / f"{contract_type.__name__}.json"
            _write_json(contract_type.model_json_schema(), target)
        print(output.resolve())
        return 0
    if args.command == "llm-config-validate":
        gateway_config = load_gateway_config(args.config.resolve())
        _write_json({"valid": True, **redacted_gateway_config(gateway_config)})
        return 0
    if args.command == "llm-provider-list":
        gateway_config = load_gateway_config(args.config.resolve())
        redacted = redacted_gateway_config(gateway_config)
        _write_json(
            {
                "default_profile": redacted["default_profile"],
                "routing": redacted["routing"],
                "profiles": redacted["profiles"],
            }
        )
        return 0
    if args.command == "llm-secret-set":
        store = DPAPISecretStore(layout.path("secrets", "llm"))
        secret = getpass.getpass("Provider credential: ")
        store.put(args.reference, secret)
        _write_json({"reference": args.reference, "configured": True})
        return 0
    if args.command == "llm-secret-status":
        store = DPAPISecretStore(layout.path("secrets", "llm"))
        present = store.contains(args.reference)
        readable = False
        if present:
            try:
                readable = store.get(args.reference) is not None
            except OSError:
                readable = False
        _write_json(
            {
                "reference": args.reference,
                "configured": present and readable,
                "present": present,
                "readable_by_current_identity": readable,
            }
        )
        return 0
    if args.command == "llm-companion-evaluate":
        project_root = Path(__file__).resolve().parents[3]
        config_root = (project_root / "config").resolve()
        cases_path = args.cases.resolve()
        rubric_path = args.rubric.resolve()
        for label, path in (("case pack", cases_path), ("rubric", rubric_path)):
            if not path.is_relative_to(config_root):
                raise ValueError(f"{label} must be under {config_root}")
        cases = load_companion_cases(cases_path)
        if args.case_id is not None and args.limit is not None:
            raise ValueError("--case-id and --limit cannot be combined")
        cases = select_companion_cases(cases, args.case_id)
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("evaluation limit must be positive")
            cases = cases[: args.limit]
        gateway_config = load_gateway_config(args.config.resolve())
        secrets = DPAPISecretStore(layout.path("secrets", "llm"))
        gateway = LLMGateway(
            gateway_config,
            build_providers(gateway_config, secrets),
        )
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"llm-companion-{run_id}")
        try:
            summary = evaluate_companion_gateway(
                gateway=gateway,
                cases=cases,
                rubric=rubric_path.read_text(encoding="utf-8-sig"),
                output_directory=output,
            )
        except ProviderError as provider_error:
            _write_json(
                {
                    "status": "failed",
                    "error_code": provider_error.code.value,
                    "message": str(provider_error),
                }
            )
            return 2
        _write_json({"output_dir": str(output), **summary})
        return 0
    if args.command == "text-session":
        project_root = Path(__file__).resolve().parents[3]
        config_root = (project_root / "config").resolve()
        rubric_path = args.rubric.resolve()
        if not rubric_path.is_relative_to(config_root):
            raise ValueError(f"rubric must be under {config_root}")
        gateway_config = load_gateway_config(args.config.resolve())
        secrets = DPAPISecretStore(layout.path("secrets", "llm"))
        gateway = LLMGateway(
            gateway_config,
            build_providers(gateway_config, secrets),
        )
        session_id = uuid4()
        audit = JsonlSessionAuditLog(
            layout.path(
                "audit",
                "sessions",
                f"{session_id}.jsonl",
                create_parent=True,
            ),
            session_id,
        )
        session = ConversationSession(
            gateway=gateway,
            rubric=rubric_path.read_text(encoding="utf-8-sig"),
            audit=audit,
            session_id=session_id,
        )
        print("Jarvis text session (simulation only). /state shows state; /quit exits.")
        while True:
            try:
                user_text = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                session.close("input_closed")
                print("\nSession closed.")
                return 0
            if not user_text:
                continue
            if user_text.casefold() in {"/quit", "/exit"}:
                session.close("user_exit")
                print("Session closed.")
                return 0
            if user_text.casefold() == "/state":
                _write_json(session.snapshot())
                continue
            try:
                result = session.process(user_text)
            except ProviderError as provider_error:
                print(f"Jarvis unavailable: {provider_error.code.value}")
                continue
            if result.reply:
                print(f"Jarvis> {result.reply}")
            if result.plan_rejection:
                print(f"Guardrail> rejected: {result.plan_rejection}")
            for record in result.simulations:
                print(f"Simulation> {record.disposition}: {record.action} {record.resource}")
    if args.command == "model-verify":
        errors = verify_model(load_manifest(args.manifest), layout)
        if errors:
            for error in errors:
                print(error)
            return 1
        print("model verified")
        return 0
    if args.command == "corpus-validate":
        _write_json(summarize_corpus(load_corpus(args.manifest)))
        return 0
    if args.command == "corpus-create":
        dataset_root = layout.path("datasets", "speech").resolve()
        output = args.output.resolve()
        if not output.is_relative_to(dataset_root):
            raise ValueError(f"corpus manifest must be under {dataset_root}")
        entries = build_phase1_corpus()
        write_corpus(entries, output)
        _write_json({"manifest": str(output), **summarize_corpus(entries)})
        return 0
    if args.command == "corpus-record":
        dataset_root = layout.path("datasets", "speech").resolve()
        corpus_root = args.corpus_root.resolve()
        manifest = args.manifest.resolve()
        if corpus_root != dataset_root:
            raise ValueError(f"corpus root must be {dataset_root}")
        if not manifest.is_relative_to(corpus_root):
            raise ValueError(f"corpus manifest must be under {corpus_root}")
        summary = record_corpus_interactive(
            load_corpus(manifest),
            corpus_root,
            MciWaveRecorder(),
            overwrite=args.overwrite,
            start_at=args.start_at,
            limit=args.limit,
        )
        _write_json(summary)
        return 0
    if args.command == "dialogue-corpus-create":
        dataset_root = layout.path("datasets", "speech").resolve()
        output = args.output.resolve()
        speech_output = args.speech_output.resolve()
        if not output.is_relative_to(dataset_root):
            raise ValueError(f"dialogue manifest must be under {dataset_root}")
        if not speech_output.is_relative_to(dataset_root):
            raise ValueError(f"dialogue speech manifest must be under {dataset_root}")
        scenarios = build_phase1_dialogues()
        speech_entries = build_phase1_dialogue_speech()
        write_dialogues(scenarios, output)
        write_dialogue_speech(speech_entries, speech_output)
        _write_json(
            {
                "dialogue_manifest": str(output),
                "speech_manifest": str(speech_output),
                "dialogue": summarize_dialogues(scenarios),
                "speech": summarize_dialogue_speech(speech_entries),
            }
        )
        return 0
    if args.command == "dialogue-corpus-validate":
        _write_json(summarize_dialogues(load_dialogues(args.manifest)))
        return 0
    if args.command == "dialogue-speech-validate":
        _write_json(summarize_dialogue_speech(load_dialogue_speech(args.manifest)))
        return 0
    if args.command == "dialogue-speech-record":
        dataset_root = layout.path("datasets", "speech").resolve()
        corpus_root = args.corpus_root.resolve()
        manifest = args.manifest.resolve()
        session_output = args.session_output.resolve()
        if corpus_root != dataset_root:
            raise ValueError(f"corpus root must be {dataset_root}")
        if not manifest.is_relative_to(corpus_root):
            raise ValueError(f"dialogue speech manifest must be under {corpus_root}")
        if not session_output.is_relative_to(corpus_root):
            raise ValueError(f"recording session output must be under {corpus_root}")
        summary = record_corpus_interactive(
            load_dialogue_speech(manifest),
            corpus_root,
            MciWaveRecorder(),
            overwrite=args.overwrite,
            start_at=args.start_at,
            limit=args.limit,
        )
        summary["source_manifest_sha256"] = sha256_file(manifest)
        _write_json(summary, session_output)
        _write_json({"session_output": str(session_output), **summary})
        return 0
    if args.command == "dialogue-session-consolidate":
        dataset_root = layout.path("datasets", "speech").resolve()
        corpus_root = args.corpus_root.resolve()
        manifest = args.manifest.resolve()
        dialogues = args.dialogues.resolve()
        sessions = args.sessions.resolve()
        output = args.output.resolve()
        stt_output = args.stt_output.resolve()
        if corpus_root != dataset_root:
            raise ValueError(f"corpus root must be {dataset_root}")
        for label, path in (
            ("speech manifest", manifest),
            ("dialogue manifest", dialogues),
            ("session directory", sessions),
            ("evaluation output", output),
            ("STT output", stt_output),
        ):
            if not path.is_relative_to(corpus_root):
                raise ValueError(f"{label} must be under {corpus_root}")
        if not sessions.is_dir():
            raise ValueError(f"session directory not found: {sessions}")
        session_paths = sorted(sessions.glob("*.json"))
        if not session_paths:
            raise ValueError("session directory contains no JSON sessions")
        evaluation, acoustic, summary = consolidate_dialogue_sessions(
            load_dialogue_speech(manifest),
            load_dialogues(dialogues),
            session_paths,
            corpus_root,
        )
        write_evaluation_manifest(evaluation, output)
        write_corpus(acoustic, stt_output)
        _write_json(
            {
                **summary,
                "evaluation_output": str(output),
                "stt_output": str(stt_output),
            }
        )
        return 0
    if args.command == "dialogue-semantic-evaluate":
        dataset_root = layout.path("datasets", "speech").resolve()
        benchmark_root = layout.path("benchmarks", "results").resolve()
        evaluation_path = args.evaluation.resolve()
        dialogue_path = args.dialogues.resolve()
        output_dir = args.output_dir.resolve()
        transcripts_path = args.transcripts.resolve() if args.transcripts else None
        if not evaluation_path.is_relative_to(dataset_root):
            raise ValueError(f"evaluation manifest must be under {dataset_root}")
        if not dialogue_path.is_relative_to(dataset_root):
            raise ValueError(f"dialogue manifest must be under {dataset_root}")
        if not output_dir.is_relative_to(benchmark_root):
            raise ValueError(f"semantic output must be under {benchmark_root}")
        if transcripts_path is not None and not transcripts_path.is_relative_to(
            layout.root.resolve()
        ):
            raise ValueError(f"transcripts must be under {layout.root.resolve()}")
        semantic_results, summary = evaluate_semantics(
            load_evaluation_manifest(evaluation_path),
            load_dialogues(dialogue_path),
            load_transcripts(transcripts_path) if transcripts_path else None,
        )
        write_semantic_report(semantic_results, summary, output_dir)
        _write_json({"output_dir": str(output_dir), **summary})
        return 0
    if args.command == "corpus-normalize":
        dataset_root = layout.path("datasets", "speech").resolve()
        corpus_root = args.corpus_root.resolve()
        manifest = args.manifest.resolve()
        output_manifest = args.output_manifest.resolve()
        if corpus_root != dataset_root:
            raise ValueError(f"corpus root must be {dataset_root}")
        if not manifest.is_relative_to(corpus_root):
            raise ValueError(f"corpus manifest must be under {corpus_root}")
        if not output_manifest.is_relative_to(corpus_root):
            raise ValueError(f"output manifest must be under {corpus_root}")
        derived, results = normalize_corpus(load_corpus(manifest), corpus_root, args.output_prefix)
        write_corpus(derived, output_manifest)
        gains = [item.gain_db for item in results]
        _write_json(
            {
                "schema_version": "1.0",
                "processed": len(results),
                "output_manifest": str(output_manifest),
                "median_gain_db": statistics.median(gains) if gains else None,
                "maximum_gain_db": max(gains) if gains else None,
                "clipped_samples": sum(item.clipped_samples for item in results),
            }
        )
        return 0
    if args.command == "qwen-semantic-benchmark":
        project_root = Path(__file__).resolve().parents[3]
        engine_root = layout.path("engines", "llm").resolve()
        model_root = layout.path("models", "llm").resolve()
        config_root = (project_root / "config" / "semantic-decoder").resolve()
        executable = args.executable.resolve()
        model = args.model.resolve()
        cases = args.cases.resolve()
        rubric = args.rubric.resolve()
        codebooks = args.codebooks.resolve()
        grammar = args.grammar.resolve()
        if not executable.is_relative_to(engine_root):
            raise ValueError(f"executable must be under {engine_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        for label, path in (
            ("case pack", cases),
            ("rubric", rubric),
            ("codebooks", codebooks),
            ("grammar", grammar),
        ):
            if not path.is_relative_to(config_root):
                raise ValueError(f"{label} must be under {config_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        qwen_config = QwenServerConfig(
            executable=executable,
            model=model,
            grammar=grammar,
            threads=args.threads,
            context_size=args.context_size,
            batch_size=args.batch_size,
            micro_batch_size=args.micro_batch_size,
            max_output_tokens=args.max_output_tokens,
            startup_timeout_seconds=args.startup_timeout,
            request_timeout_seconds=args.request_timeout,
        )
        selected_cases = [
            case
            for case in load_decoder_cases(cases)
            if args.suite == "all" or case.suite == args.suite
        ]
        loaded_rubric = rubric.read_text(encoding="utf-8-sig")
        loaded_codebooks = json.loads(codebooks.read_text(encoding="utf-8-sig"))
        with QwenServerAdapter(qwen_config) as qwen_server:
            if args.mode == "core":
                summary = benchmark_qwen_core(
                    server=qwen_server,
                    cases=selected_cases,
                    rubric=loaded_rubric,
                    codebooks=loaded_codebooks,
                    output_directory=output,
                )
            else:
                summary = benchmark_qwen_semantics(
                    server=qwen_server,
                    cases=selected_cases,
                    rubric=loaded_rubric,
                    codebooks=loaded_codebooks,
                    stability_requests=args.stability_requests,
                    output_directory=output,
                )
        _write_json({"output_dir": str(output), **summary})
        return 0
    if args.command == "deterministic-semantic-benchmark":
        project_root = Path(__file__).resolve().parents[3]
        config_root = (project_root / "config" / "semantic-decoder").resolve()
        cases = args.cases.resolve()
        codebooks = args.codebooks.resolve()
        for label, path in (("case pack", cases), ("codebooks", codebooks)):
            if not path.is_relative_to(config_root):
                raise ValueError(f"{label} must be under {config_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        summary = benchmark_deterministic_semantics(
            cases=load_decoder_cases(cases),
            codebooks=json.loads(codebooks.read_text(encoding="utf-8-sig")),
            output_directory=output,
            repetitions=args.repetitions,
        )
        _write_json({"output_dir": str(output), **summary})
        return 0
    if args.command == "stt-whisper-benchmark":
        engine_root = layout.path("engines", "stt").resolve()
        model_root = layout.path("models", "stt").resolve()
        corpus_root = layout.path("datasets", "speech").resolve()
        executable = args.executable.resolve()
        model = args.model.resolve()
        corpus_manifest = args.corpus.resolve()
        requested_corpus_root = args.corpus_root.resolve()
        if not executable.is_relative_to(engine_root):
            raise ValueError(f"executable must be under {engine_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        if requested_corpus_root != corpus_root:
            raise ValueError(f"corpus root must be {corpus_root}")
        if not corpus_manifest.is_relative_to(corpus_root):
            raise ValueError(f"corpus manifest must be under {corpus_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        config = WhisperCppConfig(executable, model, threads=args.threads, language=args.language)
        stt_adapter = WhisperCppAdapter(config, ExecutionLimits(timeout_seconds=args.timeout))
        _write_json(
            benchmark_stt(
                engine_id=args.engine_id,
                manifest=corpus_manifest,
                corpus_root=corpus_root,
                output_directory=output,
                adapter=stt_adapter,
                corpus_language=args.corpus_language,
            )
        )
        return 0
    if args.command == "stt-whisper-server-benchmark":
        engine_root = layout.path("engines", "stt").resolve()
        model_root = layout.path("models", "stt").resolve()
        corpus_root = layout.path("datasets", "speech").resolve()
        executable = args.executable.resolve()
        model = args.model.resolve()
        corpus_manifest = args.corpus.resolve()
        requested_corpus_root = args.corpus_root.resolve()
        if not executable.is_relative_to(engine_root):
            raise ValueError(f"executable must be under {engine_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        if requested_corpus_root != corpus_root:
            raise ValueError(f"corpus root must be {corpus_root}")
        if not corpus_manifest.is_relative_to(corpus_root):
            raise ValueError(f"corpus manifest must be under {corpus_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        server_config = WhisperServerConfig(
            executable=executable,
            model=model,
            threads=args.threads,
            language=args.language,
            request_timeout_seconds=args.timeout,
        )
        with WhisperServerAdapter(server_config) as server_adapter:
            summary = benchmark_stt(
                engine_id=args.engine_id,
                manifest=corpus_manifest,
                corpus_root=corpus_root,
                output_directory=output,
                adapter=server_adapter,
                measurement_profile="resident-http-per-utterance",
                engine_metadata={"server_startup_seconds": server_adapter.startup_seconds},
                corpus_language=args.corpus_language,
            )
        _write_json(summary)
        return 0
    if args.command == "stt-faster-whisper-benchmark":
        project_root = Path(__file__).resolve().parents[3]
        engine_root = layout.path("engines", "stt").resolve()
        model_root = layout.path("models", "stt").resolve()
        corpus_root = layout.path("datasets", "speech").resolve()
        python = args.python.resolve()
        worker = args.worker.resolve()
        model = args.model_dir.resolve()
        corpus_manifest = args.corpus.resolve()
        requested_corpus_root = args.corpus_root.resolve()
        if not python.is_relative_to(engine_root):
            raise ValueError(f"worker Python must be under {engine_root}")
        if not worker.is_relative_to(project_root):
            raise ValueError(f"worker script must be under {project_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        if requested_corpus_root != corpus_root:
            raise ValueError(f"corpus root must be {corpus_root}")
        if not corpus_manifest.is_relative_to(corpus_root):
            raise ValueError(f"corpus manifest must be under {corpus_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        worker_config = FasterWhisperWorkerConfig(
            python=python,
            worker=worker,
            model=model,
            threads=args.threads,
            language=args.language,
            compute_type=args.compute_type,
            hotwords=args.hotwords,
            beam_size=args.beam_size,
            word_timestamps=args.word_timestamps,
            request_timeout_seconds=args.timeout,
        )
        memory_governor = MemoryGovernor(
            load_memory_runtime_config(project_root / "config" / "runtime" / "memory-policy.toml")
        )
        try:
            with FasterWhisperWorkerAdapter(
                worker_config,
                memory_governor=memory_governor,
                certification_mode=True,
            ) as faster_worker_adapter:
                faster_summary = benchmark_stt(
                    engine_id=args.engine_id,
                    manifest=corpus_manifest,
                    corpus_root=corpus_root,
                    output_directory=output,
                    adapter=faster_worker_adapter,
                    measurement_profile="resident-ctranslate2-per-utterance",
                    engine_metadata={
                        "worker_startup_seconds": faster_worker_adapter.startup_seconds
                    },
                    corpus_language=args.corpus_language,
                )
        except MemoryAdmissionError as error:
            _write_json(
                {
                    "status": "not_run",
                    "error_code": "memory_admission_denied",
                    "decision": error.decision.model_dump(mode="json"),
                }
            )
            return 3
        faster_summary["memory_governance"] = faster_worker_adapter.memory_evidence()
        _write_json(faster_summary, output / "summary.json")
        _write_json(faster_summary)
        return 0
    if args.command == "stt-whisper-smoke":
        engine_root = layout.path("engines", "stt").resolve()
        model_root = layout.path("models", "stt").resolve()
        dataset_root = layout.path("datasets", "speech").resolve()
        executable = args.executable.resolve()
        model = args.model.resolve()
        audio = args.audio.resolve()
        if not executable.is_relative_to(engine_root):
            raise ValueError(f"executable must be under {engine_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        if not audio.is_relative_to(dataset_root):
            raise ValueError(f"audio must be under {dataset_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"smoke-{args.engine_id}-{run_id}")
        smoke_adapter = WhisperCppAdapter(
            WhisperCppConfig(executable, model, threads=args.threads, language=args.language),
            ExecutionLimits(timeout_seconds=args.timeout),
        )
        summary = smoke_stt(smoke_adapter, audio, output)
        _write_json(summary, output / "summary.json")
        _write_json(summary)
        return 0
    if args.command == "tts-espeak-benchmark":
        engine_root = layout.path("engines", "tts").resolve()
        dataset_root = layout.path("datasets", "speech").resolve()
        executable = args.executable.resolve()
        manifest = args.manifest.resolve()
        if not executable.is_relative_to(engine_root):
            raise ValueError(f"executable must be under {engine_root}")
        if not manifest.is_relative_to(dataset_root):
            raise ValueError(f"TTS manifest must be under {dataset_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        tts_adapter = EspeakAdapter(
            EspeakConfig(executable, voice=args.voice, speed_wpm=args.speed),
            ExecutionLimits(timeout_seconds=args.timeout),
        )
        _write_json(
            benchmark_tts(
                engine_id=args.engine_id,
                manifest=manifest,
                output_directory=output,
                synthesizer=tts_adapter,
                language=args.language,
                split=args.split,
            )
        )
        return 0
    if args.command == "tts-mms-vits-benchmark":
        project_root = Path(__file__).resolve().parents[3]
        engine_root = layout.path("engines", "tts").resolve()
        model_root = layout.path("models", "tts").resolve()
        dataset_root = layout.path("datasets", "speech").resolve()
        python = args.python.resolve()
        worker = args.worker.resolve()
        model = args.model_dir.resolve()
        manifest = args.manifest.resolve()
        pronunciation_lexicon = (
            args.pronunciation_lexicon.resolve() if args.pronunciation_lexicon is not None else None
        )
        if not python.is_relative_to(engine_root):
            raise ValueError(f"worker Python must be under {engine_root}")
        if not worker.is_relative_to(project_root):
            raise ValueError(f"worker script must be under {project_root}")
        if not model.is_relative_to(model_root):
            raise ValueError(f"model must be under {model_root}")
        if not manifest.is_relative_to(dataset_root):
            raise ValueError(f"TTS manifest must be under {dataset_root}")
        if pronunciation_lexicon is not None:
            config_root = (project_root / "config" / "tts").resolve()
            if not pronunciation_lexicon.is_relative_to(config_root):
                raise ValueError(f"pronunciation lexicon must be under {config_root}")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = layout.path("benchmarks", "results", f"{args.engine_id}-{run_id}")
        mms_worker_config = MmsVitsWorkerConfig(
            python=python,
            worker=worker,
            model=model,
            threads=args.threads,
            seed=args.seed,
            speaking_rate=args.speaking_rate,
            noise_scale=args.noise_scale,
            noise_scale_duration=args.noise_scale_duration,
            pronunciation_lexicon=pronunciation_lexicon,
            startup_timeout_seconds=args.startup_timeout,
            request_timeout_seconds=args.timeout,
        )
        with MmsVitsWorkerAdapter(mms_worker_config) as worker_adapter:
            summary = benchmark_tts(
                engine_id=args.engine_id,
                manifest=manifest,
                output_directory=output,
                synthesizer=worker_adapter,
                measurement_profile="resident-vits-complete-waveform",
                engine_metadata={
                    "worker_startup_seconds": worker_adapter.startup_seconds,
                    "seed": args.seed,
                    "speaking_rate": args.speaking_rate,
                    "noise_scale": args.noise_scale,
                    "noise_scale_duration": args.noise_scale_duration,
                    "pronunciation_lexicon": (
                        pronunciation_lexicon.name if pronunciation_lexicon is not None else None
                    ),
                },
                language=args.language,
                split=args.split,
            )
        _write_json(summary)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
