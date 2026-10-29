from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import jarvis.benchmarking.qwen_semantic as qwen_module
from jarvis.benchmarking.qwen_semantic import (
    ProcessMemory,
    QwenServerAdapter,
    QwenServerConfig,
    SemanticCompletion,
    benchmark_qwen_core,
    benchmark_qwen_semantics,
    build_core_prompt,
    build_decoder_prompt,
    evidence_for_case,
    load_decoder_cases,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_PACK = PROJECT_ROOT / "config" / "semantic-decoder" / "benchmark-v1.jsonl"
CODEBOOKS = PROJECT_ROOT / "config" / "semantic-decoder" / "codebooks-v1.json"


def test_case_pack_covers_oracle_corruption_and_safety() -> None:
    cases = load_decoder_cases(CASE_PACK)

    assert len(cases) == 14
    assert sum(item.suite == "oracle" for item in cases) == 5
    assert sum(item.suite == "corrupted_stt" for item in cases) == 5
    assert sum(item.suite == "safety" for item in cases) == 4


def test_prompt_separates_trusted_state_from_untrusted_transcript() -> None:
    case = load_decoder_cases(CASE_PACK)[0]
    codebooks = json.loads(CODEBOOKS.read_text(encoding="utf-8"))

    prompt = build_decoder_prompt(case, codebooks)

    assert prompt.index("TRUSTED_CODEBOOKS_AND_STATE") < prompt.index("UNTRUSTED_STT_EVIDENCE")
    assert '"authority"' not in prompt
    assert "notepad" in prompt


def test_core_prompt_omits_packet_policy_codebooks() -> None:
    case = load_decoder_cases(CASE_PACK)[0]
    codebooks = json.loads(CODEBOOKS.read_text(encoding="utf-8"))

    prompt = build_core_prompt(case, codebooks)

    assert '"intents"' in prompt
    assert '"status"' not in prompt
    assert '"clarification_reasons"' not in prompt


def test_case_candidates_become_contract_valid_evidence() -> None:
    case = load_decoder_cases(CASE_PACK)[2]

    evidence = evidence_for_case(case)

    assert evidence.authority == "none"
    assert evidence.entity_candidates[0].canonical_value == "visual-studio-code"
    assert evidence.entity_candidates[0].evidence[0].text == "munnadi open pannadha"


def test_server_config_rejects_unbounded_output(tmp_path: Path) -> None:
    files = []
    for name in ("server.exe", "model.gguf", "packet.gbnf"):
        path = tmp_path / name
        path.write_bytes(b"fixture")
        files.append(path)

    with pytest.raises(ValueError, match="maximum output tokens"):
        QwenServerConfig(files[0], files[1], files[2], max_output_tokens=65).validate()


def test_server_config_rejects_micro_batch_larger_than_batch(tmp_path: Path) -> None:
    files = []
    for name in ("server.exe", "model.gguf", "packet.gbnf"):
        path = tmp_path / name
        path.write_bytes(b"fixture")
        files.append(path)

    with pytest.raises(ValueError, match="micro-batch"):
        QwenServerConfig(
            files[0], files[1], files[2], batch_size=32, micro_batch_size=64
        ).validate()


class _FakeServer:
    def __init__(self, cases: list[Any], model: Path) -> None:
        self.config = SimpleNamespace(model=model)
        self.startup_seconds = 2.5
        self.memory_after_load = ProcessMemory(5_000_000_000, 5_100_000_000, 8_000_000_000)
        self.peak_memory_during_load = ProcessMemory(5_100_000_000, 5_200_000_000, 8_100_000_000)
        self.system_available_before_start_bytes = 9_000_000_000
        self.system_available_after_load_bytes = 4_000_000_000
        self.system_minimum_available_during_load_bytes = 3_900_000_000
        self.pagefile_used_before_start_bytes = 1_000_000_000
        self.pagefile_used_after_load_bytes = 1_200_000_000
        self.pagefile_peak_used_during_load_bytes = 1_220_000_000
        self._cases = cases

    def complete(self, _system_prompt: str, user_prompt: str) -> SemanticCompletion:
        case = next(item for item in self._cases if item.hypothesis in user_prompt)
        content = json.dumps(case.expected.to_wire(), separators=(",", ":"))
        memory = ProcessMemory(5_000_000_000, 5_100_000_000, 8_000_000_000)
        peak = ProcessMemory(5_200_000_000, 5_300_000_000, 8_200_000_000)
        return SemanticCompletion(
            content=content,
            elapsed_seconds=0.4,
            idle_memory=memory,
            peak_memory=peak,
            final_memory=memory,
            system_available_before_bytes=4_000_000_000,
            system_available_after_bytes=3_950_000_000,
            system_minimum_available_bytes=3_900_000_000,
            pagefile_used_before_bytes=1_200_000_000,
            pagefile_used_after_bytes=1_210_000_000,
            pagefile_peak_used_bytes=1_215_000_000,
            prompt_tokens=300,
            generated_tokens=20,
            predicted_tokens_per_second=50.0,
        )


class _FakeCoreServer(_FakeServer):
    def complete(self, _system_prompt: str, user_prompt: str) -> SemanticCompletion:
        case = next(item for item in self._cases if item.hypothesis in user_prompt)
        full = super().complete(_system_prompt, user_prompt)
        return SemanticCompletion(
            content=json.dumps(
                {"i": case.expected.intent_id, "p": case.expected.slots},
                separators=(",", ":"),
            ),
            elapsed_seconds=full.elapsed_seconds,
            idle_memory=full.idle_memory,
            peak_memory=full.peak_memory,
            final_memory=full.final_memory,
            system_available_before_bytes=full.system_available_before_bytes,
            system_available_after_bytes=full.system_available_after_bytes,
            system_minimum_available_bytes=full.system_minimum_available_bytes,
            pagefile_used_before_bytes=full.pagefile_used_before_bytes,
            pagefile_used_after_bytes=full.pagefile_used_after_bytes,
            pagefile_peak_used_bytes=full.pagefile_peak_used_bytes,
            prompt_tokens=full.prompt_tokens,
            generated_tokens=full.generated_tokens,
            predicted_tokens_per_second=full.predicted_tokens_per_second,
        )


def test_benchmark_reports_quality_ram_and_stability(tmp_path: Path) -> None:
    cases = load_decoder_cases(CASE_PACK)
    codebooks = json.loads(CODEBOOKS.read_text(encoding="utf-8"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fixture model")
    server: Any = _FakeServer(cases, model)

    summary = benchmark_qwen_semantics(
        server=server,
        cases=cases,
        rubric="fixture rubric",
        codebooks=codebooks,
        stability_requests=3,
        output_directory=tmp_path / "results",
    )

    assert summary["oracle_exact_accuracy"] == 1.0
    assert summary["schema_valid_rate"] == 1.0
    assert summary["json_syntax_valid_rate"] == 1.0
    assert summary["semantic_packet_valid_rate"] == 1.0
    assert summary["safe_abstention_rate"] == 1.0
    assert summary["peak_rss_bytes"] == 5_200_000_000
    assert summary["stability_requests"] == 3
    assert summary["stability_unique_outputs"] == 1
    assert (tmp_path / "results" / "report.md").is_file()


def test_core_ablation_measures_intent_and_slots(tmp_path: Path) -> None:
    cases = [case for case in load_decoder_cases(CASE_PACK) if case.suite == "oracle"]
    codebooks = json.loads(CODEBOOKS.read_text(encoding="utf-8"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fixture model")
    server: Any = _FakeCoreServer(cases, model)

    summary = benchmark_qwen_core(
        server=server,
        cases=cases,
        rubric="core rubric",
        codebooks=codebooks,
        output_directory=tmp_path / "core-results",
    )

    assert summary["core_exact_accuracy"] == 1.0
    assert summary["core_gate_valid_rate"] == 1.0
    assert summary["intent_accuracy"] == 1.0
    assert summary["slot_exact_accuracy"] == 1.0


def server_config(tmp_path: Path, **updates: Any) -> QwenServerConfig:
    paths = []
    for name in ("server.exe", "model.gguf", "packet.gbnf"):
        path = tmp_path / name
        path.write_text("root ::= '{}'", encoding="utf-8")
        paths.append(path)
    values: dict[str, Any] = {
        "executable": paths[0],
        "model": paths[1],
        "grammar": paths[2],
    }
    values.update(updates)
    return QwenServerConfig(**values)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"threads": 0}, "threads"),
        ({"context_size": 128}, "context size"),
        ({"batch_size": 0}, "batch size"),
        ({"startup_timeout_seconds": 0}, "timeouts"),
        ({"response_bytes": 1024}, "byte limit"),
    ],
)
def test_server_config_rejects_all_invalid_limits(
    tmp_path: Path, updates: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        server_config(tmp_path, **updates).validate()


def test_server_config_rejects_missing_files(tmp_path: Path) -> None:
    config = server_config(tmp_path)
    config.executable.unlink()
    with pytest.raises(FileNotFoundError, match="llama server"):
        config.validate()


class _HttpResponse:
    def __init__(self, payload: bytes = b"{}", status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> _HttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


class _Process:
    def __init__(self, *, running: bool = True, wait_timeout: bool = False) -> None:
        self.pid = 77
        self.returncode = None if running else 9
        self.running = running
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if self.running else self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout: float) -> int:
        if self.wait_timeout and not self.killed:
            raise subprocess.TimeoutExpired("server", timeout)
        self.running = False
        return 0


def install_resource_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = ProcessMemory(10, 20, 30)
    monkeypatch.setattr(qwen_module, "_process_memory", lambda _process: memory)
    monkeypatch.setattr(
        qwen_module.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(available=8_000_000_000),
    )
    monkeypatch.setattr(
        qwen_module.psutil,
        "swap_memory",
        lambda: SimpleNamespace(used=1_000_000_000),
    )
    monkeypatch.setattr(qwen_module.psutil, "Process", lambda _pid: object())


def test_server_adapter_starts_measures_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _Process(wait_timeout=True)
    install_resource_fakes(monkeypatch)
    monkeypatch.setattr(qwen_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        qwen_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HttpResponse(status=200),
    )
    adapter = QwenServerAdapter(server_config(tmp_path))

    adapter.start()

    assert adapter.endpoint.startswith("http://127.0.0.1:")
    assert adapter.memory_after_load == ProcessMemory(10, 20, 30)
    with pytest.raises(RuntimeError, match="already running"):
        adapter.start()
    adapter.close()
    assert process.terminated is True
    assert process.killed is True
    with pytest.raises(RuntimeError, match="not running"):
        _ = adapter.endpoint


def test_server_adapter_reports_startup_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _Process(running=False)
    install_resource_fakes(monkeypatch)
    monkeypatch.setattr(qwen_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    adapter = QwenServerAdapter(server_config(tmp_path))

    with pytest.raises(RuntimeError, match="exited during startup"):
        adapter.start()


def completion_payload(content: object = "{}") -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 12.0, "completion_tokens": 3},
            "timings": {"predicted_per_second": 9.5},
        }
    ).encode()


def running_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> QwenServerAdapter:
    install_resource_fakes(monkeypatch)
    monkeypatch.setattr(
        qwen_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HttpResponse(payload),
    )
    adapter = QwenServerAdapter(server_config(tmp_path))
    adapter._process = _Process()
    adapter._tracked = object()  # type: ignore[assignment]
    adapter._port = 1234
    return adapter


def test_server_adapter_completion_parses_bounded_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = running_adapter(tmp_path, monkeypatch, completion_payload('{"s":0}'))

    result = adapter.complete("system", "user")

    assert result.content == '{"s":0}'
    assert result.prompt_tokens == 12
    assert result.generated_tokens == 3
    assert result.predicted_tokens_per_second == 9.5
    assert result.peak_memory == ProcessMemory(10, 20, 30)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"choices":[]}', "no completion choice"),
        (b'{"choices":[{"message":{}}]}', "no text content"),
    ],
)
def test_server_adapter_rejects_invalid_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    message: str,
) -> None:
    adapter = running_adapter(tmp_path, monkeypatch, payload)
    with pytest.raises(ValueError, match=message):
        adapter.complete("system", "user")


def test_server_adapter_rejects_oversized_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = running_adapter(tmp_path, monkeypatch, b"x" * 4097)
    adapter.config = server_config(tmp_path, response_bytes=4096)
    with pytest.raises(RuntimeError, match="byte limit"):
        adapter.complete("system", "user")


def test_server_adapter_requires_running_process(tmp_path: Path) -> None:
    adapter = QwenServerAdapter(server_config(tmp_path))
    with pytest.raises(RuntimeError, match="not running"):
        adapter.complete("system", "user")
