"""Resident llama.cpp semantic-decoder quality and resource benchmark."""

from __future__ import annotations

import json
import os
import socket
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import psutil  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.contracts.models import (
    EntityCandidate,
    EvidenceSpan,
    PrivacyMode,
    SemanticPacket,
    SemanticStatusCode,
    TranscriptEvidence,
    TranscriptHypothesis,
)
from jarvis.understanding.semantic_gate import SemanticGateError, expand_semantic_packet

CaseSuite = Literal["oracle", "corrupted_stt", "safety"]


class DecoderCandidate(BaseModel):
    """One evidence-linked entity candidate supplied to the decoder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: int = Field(gt=0)
    slot: str = Field(min_length=1)
    canonical_value: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)


class SemanticDecoderCase(BaseModel):
    """Versioned semantic-decoder benchmark case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    suite: CaseSuite
    hypothesis: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidates: tuple[DecoderCandidate, ...] = ()
    available_reference_ids: tuple[int, ...] = ()
    pending_operation: bool = False
    expected: SemanticPacket

    @model_validator(mode="after")
    def validate_case(self) -> SemanticDecoderCase:
        candidate_ids = {item.candidate_id for item in self.candidates}
        if len(candidate_ids) != len(self.candidates):
            raise ValueError("candidate IDs must be unique within a case")
        for candidate in self.candidates:
            if candidate.surface not in self.hypothesis:
                raise ValueError(
                    f"candidate surface is absent from hypothesis: {candidate.surface}"
                )
        if not set(self.expected.slots.values()).issubset(candidate_ids):
            raise ValueError("expected packet selects an unsupplied candidate")
        if not set(self.expected.references).issubset(self.available_reference_ids):
            raise ValueError("expected packet selects an unavailable reference")
        return self


class SemanticCoreSelection(BaseModel):
    """Minimal intent/entity output used to isolate language understanding."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    intent_id: int = Field(alias="i", gt=0)
    slots: dict[str, int] = Field(default_factory=dict, alias="p", max_length=16)

    @model_validator(mode="after")
    def validate_slots(self) -> SemanticCoreSelection:
        if any(not name.strip() for name in self.slots):
            raise ValueError("slot names must be non-empty")
        if any(candidate_id <= 0 for candidate_id in self.slots.values()):
            raise ValueError("slot candidate IDs must be positive")
        return self

    def to_wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


@dataclass(frozen=True, slots=True)
class QwenServerConfig:
    executable: Path
    model: Path
    grammar: Path
    threads: int = 4
    context_size: int = 1024
    batch_size: int = 128
    micro_batch_size: int = 64
    max_output_tokens: int = 48
    seed: int = 42
    startup_timeout_seconds: float = 300.0
    request_timeout_seconds: float = 120.0
    response_bytes: int = 256 * 1024

    def validate(self) -> None:
        for label, path in (
            ("llama server executable", self.executable),
            ("GGUF model", self.model),
            ("grammar", self.grammar),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"{label} not found: {path}")
        if not 1 <= self.threads <= 8:
            raise ValueError("threads must be between 1 and 8")
        if not 256 <= self.context_size <= 4096:
            raise ValueError("context size must be between 256 and 4096")
        if not 1 <= self.batch_size <= 2048:
            raise ValueError("batch size must be between 1 and 2048")
        if not 1 <= self.micro_batch_size <= self.batch_size:
            raise ValueError("micro-batch size must be between 1 and batch size")
        if not 1 <= self.max_output_tokens <= 64:
            raise ValueError("maximum output tokens must be between 1 and 64")
        if self.startup_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("server timeouts must be positive")
        if self.response_bytes < 4096:
            raise ValueError("response byte limit is too small")


@dataclass(frozen=True, slots=True)
class ProcessMemory:
    rss_bytes: int
    private_bytes: int
    virtual_bytes: int


@dataclass(frozen=True, slots=True)
class SemanticCompletion:
    content: str
    elapsed_seconds: float
    idle_memory: ProcessMemory
    peak_memory: ProcessMemory
    final_memory: ProcessMemory
    system_available_before_bytes: int
    system_available_after_bytes: int
    system_minimum_available_bytes: int
    pagefile_used_before_bytes: int
    pagefile_used_after_bytes: int
    pagefile_peak_used_bytes: int
    prompt_tokens: int | None
    generated_tokens: int | None
    predicted_tokens_per_second: float | None


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_memory(process: psutil.Process) -> ProcessMemory:
    totals = {"rss": 0, "private": 0, "vms": 0}
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    for item in processes:
        try:
            values = item.memory_info()._asdict()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        rss = int(values.get("rss", 0))
        totals["rss"] += rss
        totals["private"] += int(values.get("private", rss))
        totals["vms"] += int(values.get("vms", 0))
    return ProcessMemory(totals["rss"], totals["private"], totals["vms"])


def _maximum_memory(left: ProcessMemory, right: ProcessMemory) -> ProcessMemory:
    return ProcessMemory(
        max(left.rss_bytes, right.rss_bytes),
        max(left.private_bytes, right.private_bytes),
        max(left.virtual_bytes, right.virtual_bytes),
    )


def _integer_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


class QwenServerAdapter:
    """Own a loopback-only llama-server and measure its resident memory."""

    def __init__(self, config: QwenServerConfig) -> None:
        config.validate()
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._tracked: psutil.Process | None = None
        self._port: int | None = None
        self.startup_seconds: float | None = None
        self.memory_before_start: ProcessMemory | None = None
        self.memory_after_load: ProcessMemory | None = None
        self.peak_memory_during_load: ProcessMemory | None = None
        self.system_available_before_start_bytes: int | None = None
        self.system_available_after_load_bytes: int | None = None
        self.system_minimum_available_during_load_bytes: int | None = None
        self.pagefile_used_before_start_bytes: int | None = None
        self.pagefile_used_after_load_bytes: int | None = None
        self.pagefile_peak_used_during_load_bytes: int | None = None

    def __enter__(self) -> QwenServerAdapter:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def endpoint(self) -> str:
        if self._port is None:
            raise RuntimeError("Qwen server is not running")
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("Qwen server is already running")
        port = _free_local_port()
        command = [
            str(self.config.executable),
            "--model",
            str(self.config.model),
            "--threads",
            str(self.config.threads),
            "--ctx-size",
            str(self.config.context_size),
            "--batch-size",
            str(self.config.batch_size),
            "--ubatch-size",
            str(self.config.micro_batch_size),
            "--parallel",
            "1",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.system_available_before_start_bytes = psutil.virtual_memory().available
        self.pagefile_used_before_start_bytes = psutil.swap_memory().used
        load_peak = ProcessMemory(0, 0, 0)
        minimum_available = self.system_available_before_start_bytes
        peak_pagefile = self.pagefile_used_before_start_bytes
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creation_flags,
        )
        self._process = process
        self._tracked = psutil.Process(process.pid)
        self._port = port
        self.memory_before_start = ProcessMemory(0, 0, 0)
        deadline = started + self.config.startup_timeout_seconds
        try:
            while time.perf_counter() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"llama-server exited during startup with code {process.returncode}"
                    )
                load_peak = _maximum_memory(load_peak, _process_memory(self._tracked))
                minimum_available = min(minimum_available, psutil.virtual_memory().available)
                peak_pagefile = max(peak_pagefile, psutil.swap_memory().used)
                try:
                    with urllib.request.urlopen(
                        f"{self.endpoint}/health", timeout=0.75
                    ) as response:
                        if response.status == 200:
                            self.startup_seconds = time.perf_counter() - started
                            self.memory_after_load = _process_memory(self._tracked)
                            self.peak_memory_during_load = _maximum_memory(
                                load_peak, self.memory_after_load
                            )
                            self.system_available_after_load_bytes = (
                                psutil.virtual_memory().available
                            )
                            self.system_minimum_available_during_load_bytes = min(
                                minimum_available,
                                self.system_available_after_load_bytes,
                            )
                            self.pagefile_used_after_load_bytes = psutil.swap_memory().used
                            self.pagefile_peak_used_during_load_bytes = max(
                                peak_pagefile, self.pagefile_used_after_load_bytes
                            )
                            return
                except (OSError, TimeoutError, urllib.error.URLError):
                    time.sleep(0.1)
            raise TimeoutError("llama-server did not become healthy before the deadline")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tracked = None
        self._port = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)

    def complete(self, system_prompt: str, user_prompt: str) -> SemanticCompletion:
        if self._process is None or self._tracked is None:
            raise RuntimeError("Qwen server is not running")
        grammar = self.config.grammar.read_text(encoding="utf-8")
        request_body = json.dumps(
            {
                "model": "jarvis-qwen-semantic-decoder",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "seed": self.config.seed,
                "max_tokens": self.config.max_output_tokens,
                "stream": False,
                "cache_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False},
                "grammar": grammar,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        idle = _process_memory(self._tracked)
        peak = [idle]
        minimum_available = [psutil.virtual_memory().available]
        peak_pagefile = [psutil.swap_memory().used]
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(0.025):
                peak[0] = _maximum_memory(peak[0], _process_memory(self._tracked))
                minimum_available[0] = min(minimum_available[0], psutil.virtual_memory().available)
                peak_pagefile[0] = max(peak_pagefile[0], psutil.swap_memory().used)

        system_before = psutil.virtual_memory().available
        pagefile_before = psutil.swap_memory().used
        sampler = threading.Thread(target=sample, daemon=True)
        started = time.perf_counter()
        sampler.start()
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.request_timeout_seconds
            ) as response:
                payload_bytes = response.read(self.config.response_bytes + 1)
                if len(payload_bytes) > self.config.response_bytes:
                    raise RuntimeError("Qwen server response exceeded the byte limit")
        finally:
            stop.set()
            sampler.join(timeout=1.0)
        elapsed = time.perf_counter() - started
        final = _process_memory(self._tracked)
        peak[0] = _maximum_memory(peak[0], final)
        payload = json.loads(payload_bytes.decode("utf-8"))
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("llama-server response has no completion choice")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("llama-server response has no text content")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
        return SemanticCompletion(
            content=str(message["content"]),
            elapsed_seconds=elapsed,
            idle_memory=idle,
            peak_memory=peak[0],
            final_memory=final,
            system_available_before_bytes=system_before,
            system_available_after_bytes=psutil.virtual_memory().available,
            system_minimum_available_bytes=minimum_available[0],
            pagefile_used_before_bytes=pagefile_before,
            pagefile_used_after_bytes=psutil.swap_memory().used,
            pagefile_peak_used_bytes=peak_pagefile[0],
            prompt_tokens=_integer_or_none(usage.get("prompt_tokens")),
            generated_tokens=_integer_or_none(usage.get("completion_tokens")),
            predicted_tokens_per_second=_float_or_none(timings.get("predicted_per_second")),
        )


def load_decoder_cases(path: Path) -> list[SemanticDecoderCase]:
    cases: list[SemanticDecoderCase] = []
    case_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = SemanticDecoderCase.model_validate_json(line)
        except ValueError as error:
            raise ValueError(f"invalid decoder case on line {line_number}: {error}") from error
        if case.case_id in case_ids:
            raise ValueError(f"duplicate decoder case: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("decoder case pack is empty")
    return cases


def build_decoder_prompt(case: SemanticDecoderCase, codebooks: dict[str, Any]) -> str:
    """Serialize trusted state separately from untrusted speech evidence."""

    trusted = {
        "status": codebooks["status"],
        "dialogue_acts": codebooks["dialogue_acts"],
        "intents": codebooks["intents"],
        "references": codebooks["references"],
        "marker_bits": codebooks["marker_bits"],
        "clarification_reasons": codebooks["clarification_reasons"],
        "required_slots": codebooks["required_slots"],
        "state": {
            "pending_operation": case.pending_operation,
            "available_reference_ids": list(case.available_reference_ids),
        },
    }
    untrusted = {
        "hypotheses": [
            {
                "hypothesis_id": "h1",
                "rank": 0,
                "text": case.hypothesis,
                "confidence": case.confidence,
                "language": "mixed",
            }
        ],
        "entity_candidates": [
            {
                "candidate_id": item.candidate_id,
                "slot": item.slot,
                "canonical_value": item.canonical_value,
                "surface": item.surface,
                "score": item.score,
            }
            for item in case.candidates
        ],
    }
    return (
        "TRUSTED_CODEBOOKS_AND_STATE\n"
        + json.dumps(trusted, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\nUNTRUSTED_STT_EVIDENCE\n"
        + json.dumps(untrusted, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\nCOMPILE_ONE_PACKET"
    )


def build_core_prompt(case: SemanticDecoderCase, codebooks: dict[str, Any]) -> str:
    """Build the smaller prompt used by the comprehension-only ablation."""

    trusted = {
        "intents": codebooks["intents"],
        "required_slots": codebooks["required_slots"],
        "pending_operation": case.pending_operation,
    }
    untrusted = {
        "text": case.hypothesis,
        "candidates": [
            {
                "id": item.candidate_id,
                "slot": item.slot,
                "value": item.canonical_value,
                "surface": item.surface,
            }
            for item in case.candidates
        ],
    }
    return (
        "TRUSTED\n"
        + json.dumps(trusted, ensure_ascii=False, separators=(",", ":"))
        + "\nUNTRUSTED_STT\n"
        + json.dumps(untrusted, ensure_ascii=False, separators=(",", ":"))
        + "\nCLASSIFY"
    )


def evidence_for_case(case: SemanticDecoderCase) -> TranscriptEvidence:
    candidates: list[EntityCandidate] = []
    for item in case.candidates:
        start = case.hypothesis.index(item.surface)
        candidates.append(
            EntityCandidate(
                candidate_id=item.candidate_id,
                slot=item.slot,
                canonical_value=item.canonical_value,
                score=item.score,
                evidence=(
                    EvidenceSpan(
                        hypothesis_id="h1",
                        start_char=start,
                        end_char=start + len(item.surface),
                        text=item.surface,
                    ),
                ),
            )
        )
    stable_id = uuid5(NAMESPACE_URL, f"jarvis:qwen:{case.case_id}")
    return TranscriptEvidence(
        session_id=stable_id,
        utterance_id=stable_id,
        emitted_monotonic_ns=0,
        engine_id="semantic-benchmark",
        hypotheses=(
            TranscriptHypothesis(
                hypothesis_id="h1",
                rank=0,
                text=case.hypothesis,
                confidence=case.confidence,
                language="mixed",
            ),
        ),
        entity_candidates=tuple(candidates),
        privacy_mode=PrivacyMode.PRIVATE,
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.9999)))
    return ordered[index]


def benchmark_qwen_semantics(
    *,
    server: QwenServerAdapter,
    cases: list[SemanticDecoderCase],
    rubric: str,
    codebooks: dict[str, Any],
    stability_requests: int,
    output_directory: Path,
) -> dict[str, Any]:
    """Measure constrained output quality, RAM, paging, latency and stability."""

    if stability_requests < 0:
        raise ValueError("stability request count cannot be negative")
    intents = {int(key): str(value) for key, value in codebooks["intents"].items()}
    references = {int(key): str(value) for key, value in codebooks["references"].items()}
    required_slots = {
        str(intent): frozenset(str(slot) for slot in slots)
        for intent, slots in codebooks["required_slots"].items()
    }
    results: list[dict[str, Any]] = []
    for case in cases:
        completion = server.complete(rubric, build_decoder_prompt(case, codebooks))
        stripped = completion.content.strip()
        json_syntax_valid = False
        semantic_packet_valid = False
        exact_packet = False
        gate_valid = False
        packet_wire: dict[str, Any] | None = None
        error: str | None = None
        error_stage: str | None = None
        try:
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                raise ValueError("decoder output must be one JSON object")
            json_syntax_valid = True
        except (json.JSONDecodeError, ValueError) as caught:
            error = str(caught)
            error_stage = "json"
        if json_syntax_valid:
            try:
                packet = SemanticPacket.model_validate(parsed)
                semantic_packet_valid = True
            except ValueError as caught:
                error = str(caught)
                error_stage = "semantic_packet"
        if semantic_packet_valid:
            try:
                packet_wire = packet.to_wire()
                exact_packet = packet_wire == case.expected.to_wire()
                expand_semantic_packet(
                    packet,
                    evidence_for_case(case),
                    intent_registry=intents,
                    reference_registry=references,
                    required_slots=required_slots,
                    minimum_candidate_score=0.70,
                    pending_operation=case.pending_operation,
                )
                gate_valid = True
            except SemanticGateError as caught:
                error = str(caught)
                error_stage = "deterministic_gate"
        safe_abstention = (
            case.expected.status is not SemanticStatusCode.ACCEPTED
            and packet_wire is not None
            and packet_wire.get("s")
            in {
                int(SemanticStatusCode.CLARIFY),
                int(SemanticStatusCode.UNKNOWN),
            }
            and gate_valid
        )
        results.append(
            {
                "case_id": case.case_id,
                "suite": case.suite,
                "raw_output": completion.content,
                "packet": packet_wire,
                "expected": case.expected.to_wire(),
                "json_syntax_valid": json_syntax_valid,
                "semantic_packet_valid": semantic_packet_valid,
                "schema_valid": semantic_packet_valid,
                "exact_packet": exact_packet,
                "gate_valid": gate_valid,
                "safe_abstention": safe_abstention,
                "error": error,
                "error_stage": error_stage,
                "elapsed_seconds": completion.elapsed_seconds,
                "idle_rss_bytes": completion.idle_memory.rss_bytes,
                "peak_rss_bytes": completion.peak_memory.rss_bytes,
                "peak_private_bytes": completion.peak_memory.private_bytes,
                "final_rss_bytes": completion.final_memory.rss_bytes,
                "system_available_delta_bytes": (
                    completion.system_available_after_bytes
                    - completion.system_available_before_bytes
                ),
                "system_available_peak_drop_bytes": max(
                    0,
                    completion.system_available_before_bytes
                    - completion.system_minimum_available_bytes,
                ),
                "pagefile_used_delta_bytes": (
                    completion.pagefile_used_after_bytes - completion.pagefile_used_before_bytes
                ),
                "pagefile_peak_increase_bytes": max(
                    0,
                    completion.pagefile_peak_used_bytes - completion.pagefile_used_before_bytes,
                ),
                "prompt_tokens": completion.prompt_tokens,
                "generated_tokens": completion.generated_tokens,
                "predicted_tokens_per_second": completion.predicted_tokens_per_second,
            }
        )

    stability_latencies: list[float] = []
    stability_rss: list[int] = []
    stability_outputs: set[str] = set()
    stability_case = cases[0]
    memory_at_stability_start = int(results[-1]["final_rss_bytes"])
    for _index in range(stability_requests):
        completion = server.complete(rubric, build_decoder_prompt(stability_case, codebooks))
        stability_latencies.append(completion.elapsed_seconds)
        stability_rss.append(completion.final_memory.rss_bytes)
        stability_outputs.add(completion.content.strip())
    final_stability_rss = stability_rss[-1] if stability_rss else memory_at_stability_start

    quality_latencies = [float(item["elapsed_seconds"]) for item in results]
    oracle = [item for item in results if item["suite"] == "oracle"]
    abstention = [
        item
        for item in results
        if item["suite"] in {"corrupted_stt", "safety"}
        and item["expected"]["s"] != int(SemanticStatusCode.ACCEPTED)
    ]
    system_available_after_load = server.system_available_after_load_bytes
    peak_private = max(int(item["peak_private_bytes"]) for item in results)
    load_pagefile_peak_increase = (
        max(
            0,
            server.pagefile_peak_used_during_load_bytes - server.pagefile_used_before_start_bytes,
        )
        if server.pagefile_peak_used_during_load_bytes is not None
        and server.pagefile_used_before_start_bytes is not None
        else None
    )
    stability_drift = final_stability_rss - memory_at_stability_start
    oracle_accuracy = (
        sum(bool(item["exact_packet"]) for item in oracle) / len(oracle) if oracle else 0.0
    )
    json_rate = sum(bool(item["json_syntax_valid"]) for item in results) / len(results)
    packet_rate = sum(bool(item["semantic_packet_valid"]) for item in results) / len(results)
    gate_rate = sum(bool(item["gate_valid"]) for item in results) / len(results)
    abstention_rate: float | None = (
        sum(bool(item["safe_abstention"]) for item in abstention) / len(abstention)
        if abstention
        else None
    )
    required_quality_rates = [oracle_accuracy, packet_rate, gate_rate]
    if abstention_rate is not None:
        required_quality_rates.append(abstention_rate)
    quality_gate_pass = all(value == 1.0 for value in required_quality_rates)
    resource_gate_pass = (
        system_available_after_load is not None
        and system_available_after_load >= 2 * 1024**3
        and peak_private <= int(7.5 * 1024**3)
        and load_pagefile_peak_increase is not None
        and load_pagefile_peak_increase <= 512 * 1024**2
        and (stability_requests < 100 or stability_drift <= 128 * 1024**2)
    )
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "model": str(server.config.model),
        "quantization": "Q4_K_M",
        "model_file_bytes": server.config.model.stat().st_size,
        "cases": len(results),
        "oracle_cases": len(oracle),
        "oracle_exact_accuracy": oracle_accuracy,
        "json_syntax_valid_rate": json_rate,
        "semantic_packet_valid_rate": packet_rate,
        "schema_valid_rate": packet_rate,
        "gate_valid_rate": gate_rate,
        "safe_abstention_rate": abstention_rate,
        "exact_packet_rate": (sum(bool(item["exact_packet"]) for item in results) / len(results)),
        "startup_seconds": server.startup_seconds,
        "idle_rss_after_load_bytes": (
            server.memory_after_load.rss_bytes if server.memory_after_load else None
        ),
        "idle_private_after_load_bytes": (
            server.memory_after_load.private_bytes if server.memory_after_load else None
        ),
        "load_peak_rss_bytes": (
            server.peak_memory_during_load.rss_bytes if server.peak_memory_during_load else None
        ),
        "load_peak_private_bytes": (
            server.peak_memory_during_load.private_bytes if server.peak_memory_during_load else None
        ),
        "system_available_after_load_bytes": system_available_after_load,
        "system_minimum_available_during_load_bytes": (
            server.system_minimum_available_during_load_bytes
        ),
        "system_available_load_delta_bytes": (
            server.system_available_after_load_bytes - server.system_available_before_start_bytes
            if server.system_available_after_load_bytes is not None
            and server.system_available_before_start_bytes is not None
            else None
        ),
        "pagefile_load_delta_bytes": (
            server.pagefile_used_after_load_bytes - server.pagefile_used_before_start_bytes
            if server.pagefile_used_after_load_bytes is not None
            and server.pagefile_used_before_start_bytes is not None
            else None
        ),
        "pagefile_load_peak_increase_bytes": load_pagefile_peak_increase,
        "peak_rss_bytes": max(int(item["peak_rss_bytes"]) for item in results),
        "peak_private_bytes": peak_private,
        "maximum_request_pagefile_increase_bytes": max(
            int(item["pagefile_peak_increase_bytes"]) for item in results
        ),
        "maximum_request_available_memory_drop_bytes": max(
            int(item["system_available_peak_drop_bytes"]) for item in results
        ),
        "warm_latency_p50_seconds": statistics.median(quality_latencies),
        "warm_latency_p95_seconds": _percentile(quality_latencies, 0.95),
        "stability_requests": stability_requests,
        "stability_unique_outputs": len(stability_outputs),
        "stability_latency_p95_seconds": _percentile(stability_latencies, 0.95),
        "stability_rss_drift_bytes": stability_drift,
        "quality_gate_pass": quality_gate_pass,
        "resource_gate_pass": resource_gate_pass,
        "certified": (
            quality_gate_pass
            and resource_gate_pass
            and stability_requests >= 100
            and len(stability_outputs) == 1
        ),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "results.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in results) + "\n",
        encoding="utf-8",
    )
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# Qwen3-8B-Tanglish Q4_K_M semantic-decoder benchmark",
        "",
        f"- Oracle exact accuracy: {summary['oracle_exact_accuracy']:.1%}",
        f"- JSON syntax validity: {summary['json_syntax_valid_rate']:.1%}",
        f"- Semantic-packet validity: {summary['semantic_packet_valid_rate']:.1%}",
        f"- Deterministic-gate validity: {summary['gate_valid_rate']:.1%}",
        "- Corrupted/safety safe abstention: "
        + (
            f"{summary['safe_abstention_rate']:.1%}"
            if summary["safe_abstention_rate"] is not None
            else "not measured"
        ),
        f"- Model load time: {summary['startup_seconds']:.3f} s",
        f"- Q4_K_M file size: {summary['model_file_bytes'] / 1_073_741_824:.3f} GiB",
        f"- Idle RSS after load: {summary['idle_rss_after_load_bytes'] / 1_073_741_824:.3f} GiB",
        f"- Load peak RSS: {summary['load_peak_rss_bytes'] / 1_073_741_824:.3f} GiB",
        f"- Peak RSS: {summary['peak_rss_bytes'] / 1_073_741_824:.3f} GiB",
        f"- Peak private bytes: {summary['peak_private_bytes'] / 1_073_741_824:.3f} GiB",
        f"- Warm p50 latency: {summary['warm_latency_p50_seconds']:.3f} s",
        f"- Warm p95 latency: {summary['warm_latency_p95_seconds']:.3f} s",
        f"- Stability requests: {stability_requests}",
        f"- Stability unique outputs: {summary['stability_unique_outputs']}",
        f"- Stability RSS drift: {summary['stability_rss_drift_bytes'] / 1_048_576:.1f} MiB",
        f"- Quality gate: {'PASS' if quality_gate_pass else 'FAIL'}",
        f"- Resource gate: {'PASS' if resource_gate_pass else 'FAIL'}",
        f"- Certified: {'yes' if summary['certified'] else 'no'}",
        "",
        "| Case | Suite | JSON | Packet | Exact | Gate | Safe abstention | Latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    report.extend(
        f"| {item['case_id']} | {item['suite']} | "
        f"{'yes' if item['json_syntax_valid'] else 'no'} | "
        f"{'yes' if item['semantic_packet_valid'] else 'no'} | "
        f"{'yes' if item['exact_packet'] else 'no'} | "
        f"{'yes' if item['gate_valid'] else 'no'} | "
        f"{'yes' if item['safe_abstention'] else 'no'} | "
        f"{item['elapsed_seconds']:.3f} |"
        for item in results
    )
    (output_directory / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def benchmark_qwen_core(
    *,
    server: QwenServerAdapter,
    cases: list[SemanticDecoderCase],
    rubric: str,
    codebooks: dict[str, Any],
    output_directory: Path,
) -> dict[str, Any]:
    """Measure intent/entity comprehension without packet policy fields."""

    if not cases:
        raise ValueError("core ablation requires at least one case")
    results: list[dict[str, Any]] = []
    intent_registry = {
        int(intent_id): str(intent) for intent_id, intent in codebooks["intents"].items()
    }
    required_slot_registry = {
        str(intent): frozenset(str(slot) for slot in slots)
        for intent, slots in codebooks["required_slots"].items()
    }
    for case in cases:
        if case.expected.intent_id is None:
            raise ValueError(f"core case has no expected intent: {case.case_id}")
        completion = server.complete(rubric, build_core_prompt(case, codebooks))
        raw = completion.content.strip()
        expected = {"i": case.expected.intent_id, "p": case.expected.slots}
        json_valid = False
        core_valid = False
        core_gate_valid = False
        predicted: dict[str, Any] | None = None
        error: str | None = None
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("core output must be one JSON object")
            json_valid = True
            selection = SemanticCoreSelection.model_validate(parsed)
            core_valid = True
            predicted = selection.to_wire()
            selected_intent = intent_registry.get(selection.intent_id)
            candidates = {item.candidate_id: item for item in case.candidates}
            required_slots = required_slot_registry.get(selected_intent or "", frozenset())
            core_gate_valid = (
                selected_intent is not None
                and frozenset(selection.slots) == required_slots
                and all(
                    candidate_id in candidates and candidates[candidate_id].slot == slot
                    for slot, candidate_id in selection.slots.items()
                )
            )
        except (json.JSONDecodeError, ValueError) as caught:
            error = str(caught)
        results.append(
            {
                "case_id": case.case_id,
                "raw_output": completion.content,
                "predicted": predicted,
                "expected": expected,
                "json_syntax_valid": json_valid,
                "core_valid": core_valid,
                "core_gate_valid": core_gate_valid,
                "intent_correct": predicted is not None and predicted["i"] == expected["i"],
                "slots_exact": predicted is not None and predicted["p"] == expected["p"],
                "core_exact": predicted == expected,
                "error": error,
                "elapsed_seconds": completion.elapsed_seconds,
                "prompt_tokens": completion.prompt_tokens,
                "generated_tokens": completion.generated_tokens,
                "peak_rss_bytes": completion.peak_memory.rss_bytes,
                "peak_private_bytes": completion.peak_memory.private_bytes,
            }
        )

    latencies = [float(item["elapsed_seconds"]) for item in results]
    count = len(results)
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "semantic_core_ablation",
        "model": str(server.config.model),
        "quantization": "Q4_K_M",
        "cases": count,
        "json_syntax_valid_rate": sum(bool(item["json_syntax_valid"]) for item in results) / count,
        "core_valid_rate": sum(bool(item["core_valid"]) for item in results) / count,
        "core_gate_valid_rate": sum(bool(item["core_gate_valid"]) for item in results) / count,
        "intent_accuracy": sum(bool(item["intent_correct"]) for item in results) / count,
        "slot_exact_accuracy": sum(bool(item["slots_exact"]) for item in results) / count,
        "core_exact_accuracy": sum(bool(item["core_exact"]) for item in results) / count,
        "startup_seconds": server.startup_seconds,
        "system_available_after_load_bytes": server.system_available_after_load_bytes,
        "peak_rss_bytes": max(int(item["peak_rss_bytes"]) for item in results),
        "peak_private_bytes": max(int(item["peak_private_bytes"]) for item in results),
        "warm_latency_p50_seconds": statistics.median(latencies),
        "warm_latency_p95_seconds": _percentile(latencies, 0.95),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "results.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in results) + "\n",
        encoding="utf-8",
    )
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


__all__ = [
    "DecoderCandidate",
    "QwenServerAdapter",
    "QwenServerConfig",
    "SemanticCoreSelection",
    "SemanticDecoderCase",
    "benchmark_qwen_core",
    "benchmark_qwen_semantics",
    "build_core_prompt",
    "build_decoder_prompt",
    "evidence_for_case",
    "load_decoder_cases",
]
