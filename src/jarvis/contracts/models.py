"""Versioned, authority-aware contracts shared by Jarvis services."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


NonEmpty = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"


class DataClass(StrEnum):
    PUBLIC = "PUBLIC"
    PERSONAL = "PERSONAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
    PROHIBITED = "PROHIBITED"


class PrivacyMode(StrEnum):
    WATCHING = "WATCHING"
    PRIVATE = "PRIVATE"
    SLEEPING = "SLEEPING"


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"


class Outcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    CANCELLED = "CANCELLED"


class LLMPrivacyClass(StrEnum):
    LOCAL_ONLY = "local_only"
    REMOTE_REDACTED = "remote_redacted"
    REMOTE_ALLOWED = "remote_allowed"


class InteractionMode(StrEnum):
    CHAT = "chat"
    ANSWER = "answer"
    CLARIFY = "clarify"
    PLAN = "plan"
    MIXED = "mixed"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    NO_ACTION = "no_action"


class ProviderKind(StrEnum):
    FAKE = "fake"
    AZURE_OPENAI = "azure_openai"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"


class ProviderState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class Task(Contract):
    task_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    goal: NonEmpty
    data_classes: frozenset[DataClass] = Field(default_factory=frozenset)


class LLMMessage(Contract):
    role: Literal["user", "assistant"]
    content: NonEmpty


class ModelCapabilities(Contract):
    streaming: bool = False
    structured_output: bool = False
    json_schema: bool = False
    vision: bool = False
    audio_input: bool = False
    usage_reporting: bool = False
    maximum_context_tokens: int | None = Field(default=None, gt=0)


class ProviderHealth(Contract):
    profile_id: NonEmpty
    provider: ProviderKind
    state: ProviderState
    checked_at: datetime = Field(default_factory=utc_now)
    latency_ms: float | None = Field(default=None, ge=0)
    detail: str | None = None


class LLMRequest(Contract):
    request_id: UUID = Field(default_factory=uuid4)
    purpose: NonEmpty
    system_instructions: NonEmpty
    messages: tuple[LLMMessage, ...] = Field(min_length=1, max_length=64)
    response_schema: NonEmpty
    context: dict[str, Any] = Field(default_factory=dict)
    privacy_class: LLMPrivacyClass
    data_classes: frozenset[DataClass] = Field(default_factory=frozenset)
    temperature: float = Field(default=0.2, ge=0, le=2)
    maximum_output_tokens: int = Field(default=800, ge=1, le=8192)
    deadline_ms: int = Field(default=30_000, ge=100, le=300_000)


class LLMUsage(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class LLMResponse(Contract):
    request_id: UUID
    profile_id: NonEmpty
    provider: ProviderKind
    model: NonEmpty
    text: str
    structured_output: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: float = Field(ge=0)
    authority: Literal["none"] = "none"


class ContextReference(Contract):
    reference_id: NonEmpty
    kind: NonEmpty
    label: NonEmpty
    observed_at: datetime = Field(default_factory=utc_now)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(Contract):
    role: Literal["user", "assistant"]
    text: NonEmpty
    occurred_at: datetime = Field(default_factory=utc_now)


class TurnContext(Contract):
    session_id: UUID
    turn_id: UUID = Field(default_factory=uuid4)
    input_text: NonEmpty
    transcript_evidence_id: UUID | None = None
    recent_turns: tuple[ConversationTurn, ...] = Field(default=(), max_length=24)
    references: tuple[ContextReference, ...] = Field(default=(), max_length=32)
    permitted_memories: tuple[NonEmpty, ...] = Field(default=(), max_length=16)
    pending_dialogue_id: UUID | None = None


class ClarificationRequest(Contract):
    field: NonEmpty
    reason: NonEmpty
    question: NonEmpty
    candidate_reference_ids: tuple[str, ...] = Field(default=(), max_length=8)


class Assumption(Contract):
    field: NonEmpty
    value: NonEmpty
    evidence_reference_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class PlanStepProposal(Contract):
    step_id: NonEmpty
    action: NonEmpty
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_reference_ids: tuple[str, ...] = Field(default=(), max_length=16)
    depends_on: tuple[str, ...] = Field(default=(), max_length=16)


class PlanProposal(Contract):
    goal: NonEmpty
    steps: tuple[PlanStepProposal, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_graph(self) -> PlanProposal:
        step_ids = {step.step_id for step in self.steps}
        if len(step_ids) != len(self.steps):
            raise ValueError("plan step IDs must be unique")
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError("plan step cannot depend on itself")
            if not set(step.depends_on).issubset(step_ids):
                raise ValueError("plan dependency references an unknown step")

        dependencies = {step.step_id: set(step.depends_on) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependencies contain a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


class MemoryProposal(Contract):
    category: NonEmpty
    content: NonEmpty
    reason: NonEmpty
    data_class: DataClass = DataClass.PERSONAL


class InteractionEnvelope(Contract):
    request_id: UUID
    mode: InteractionMode
    understood_goal: str | None = None
    reply: str = ""
    clarification: ClarificationRequest | None = None
    plan: PlanProposal | None = None
    assumptions: tuple[Assumption, ...] = Field(default=(), max_length=16)
    evidence_reference_ids: tuple[str, ...] = Field(default=(), max_length=32)
    memory_proposals: tuple[MemoryProposal, ...] = Field(default=(), max_length=8)
    authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_mode_payload(self) -> InteractionEnvelope:
        if self.mode is InteractionMode.CLARIFY:
            if self.clarification is None:
                raise ValueError("clarify interaction requires a clarification request")
            if self.plan is not None:
                raise ValueError("clarify interaction cannot contain a plan")
        elif self.clarification is not None:
            raise ValueError("only clarify interaction may contain clarification")

        if self.mode in {InteractionMode.PLAN, InteractionMode.MIXED}:
            if self.plan is None:
                raise ValueError("plan and mixed interactions require a plan")
        elif self.plan is not None:
            raise ValueError("non-plan interaction cannot contain a plan")

        if (
            self.mode
            in {
                InteractionMode.CHAT,
                InteractionMode.ANSWER,
                InteractionMode.MIXED,
            }
            and not self.reply.strip()
        ):
            raise ValueError("conversational interaction requires a reply")
        return self


class PendingDialogue(Contract):
    dialogue_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    kind: Literal["clarification", "approval"]
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    payload_digest: NonEmpty

    @model_validator(mode="after")
    def validate_expiry(self) -> PendingDialogue:
        if self.expires_at <= self.created_at:
            raise ValueError("pending dialogue must expire after creation")
        return self


class ProviderProfile(Contract):
    profile_id: NonEmpty
    provider: ProviderKind
    endpoint: str | None = None
    model: str | None = None
    deployment: str | None = None
    api_version: str | None = None
    credential_ref: str | None = None
    model_manifest: str | None = None
    remote: bool
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @model_validator(mode="after")
    def validate_provider_fields(self) -> ProviderProfile:
        if self.provider is ProviderKind.FAKE:
            return self
        if self.provider is ProviderKind.AZURE_OPENAI:
            required = (self.endpoint, self.deployment, self.api_version, self.credential_ref)
            if any(value is None for value in required):
                raise ValueError(
                    "Azure OpenAI requires endpoint, deployment, API version and credential"
                )
            if not self.remote:
                raise ValueError("Azure OpenAI profile must be remote")
        elif self.provider in {ProviderKind.OPENAI, ProviderKind.ANTHROPIC}:
            if self.model is None or self.credential_ref is None:
                raise ValueError("remote provider requires model and credential")
            if not self.remote:
                raise ValueError("OpenAI and Anthropic profiles must be remote")
            if self.provider is ProviderKind.ANTHROPIC and self.api_version is None:
                raise ValueError("Anthropic requires an explicitly configured API version")
        elif self.provider in {
            ProviderKind.OPENAI_COMPATIBLE,
            ProviderKind.OLLAMA,
            ProviderKind.LLAMA_CPP,
        }:
            if self.endpoint is None or self.model is None:
                raise ValueError("HTTP model provider requires endpoint and model")
            if self.provider is ProviderKind.LLAMA_CPP and self.model_manifest is None:
                raise ValueError("managed llama.cpp requires a model manifest")

        if self.endpoint is not None:
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("provider endpoint must be an absolute HTTP(S) URL")
            if self.remote and parsed.scheme != "https":
                raise ValueError("remote provider endpoint must use HTTPS")
            if not self.remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("local provider endpoint must use loopback")
        return self


class GatewayConfig(Contract):
    default_profile: NonEmpty
    fallback_order: tuple[str, ...] = ()
    routing: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, ProviderProfile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profiles(self) -> GatewayConfig:
        for name, profile in self.profiles.items():
            if name != profile.profile_id:
                raise ValueError("provider profile key must equal its profile ID")
        known = set(self.profiles)
        selected = {self.default_profile, *self.fallback_order, *self.routing.values()}
        if not selected.issubset(known):
            raise ValueError("gateway routing references an unknown provider profile")
        return self


class SpeechSegment(Contract):
    session_id: UUID
    utterance_id: UUID = Field(default_factory=uuid4)
    started_monotonic_ns: int = Field(ge=0)
    ended_monotonic_ns: int = Field(ge=0)
    sample_rate_hz: int = Field(gt=0)
    duration_ms: int = Field(ge=0)
    privacy_mode: PrivacyMode
    retained: bool = False

    @model_validator(mode="after")
    def validate_timing(self) -> SpeechSegment:
        if self.ended_monotonic_ns < self.started_monotonic_ns:
            raise ValueError("segment end precedes start")
        return self


class LanguageSpan(Contract):
    language: Literal["ta", "en", "other", "unknown"]
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> LanguageSpan:
        if self.end_char < self.start_char:
            raise ValueError("language span end precedes start")
        return self


class TranscriptEvent(Contract):
    session_id: UUID
    utterance_id: UUID
    emitted_monotonic_ns: int = Field(ge=0)
    state: Literal["partial", "final"]
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    language_spans: tuple[LanguageSpan, ...] = ()
    truncated: bool = False
    privacy_mode: PrivacyMode


class TranscriptHypothesis(Contract):
    hypothesis_id: NonEmpty
    rank: int = Field(ge=0, le=7)
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    average_log_probability: float | None = None
    no_speech_probability: float | None = Field(default=None, ge=0, le=1)
    language: Literal["ta", "en", "mixed", "other", "unknown"] = "unknown"


class EvidenceSpan(Contract):
    hypothesis_id: NonEmpty
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: NonEmpty

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceSpan:
        if self.end_char <= self.start_char:
            raise ValueError("evidence span must be non-empty")
        return self


class EntityCandidate(Contract):
    candidate_id: int = Field(gt=0)
    slot: NonEmpty
    canonical_value: NonEmpty
    score: float = Field(ge=0, le=1)
    evidence: tuple[EvidenceSpan, ...] = Field(min_length=1, max_length=8)


class TranscriptEvidence(Contract):
    """Untrusted acoustic/text evidence; never an executable command."""

    session_id: UUID
    utterance_id: UUID
    emitted_monotonic_ns: int = Field(ge=0)
    engine_id: NonEmpty
    hypotheses: tuple[TranscriptHypothesis, ...] = Field(min_length=1, max_length=8)
    entity_candidates: tuple[EntityCandidate, ...] = Field(default=(), max_length=32)
    language_spans: tuple[LanguageSpan, ...] = ()
    truncated: bool = False
    privacy_mode: PrivacyMode
    authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_evidence_links(self) -> TranscriptEvidence:
        hypothesis_map = {item.hypothesis_id: item for item in self.hypotheses}
        if len(hypothesis_map) != len(self.hypotheses):
            raise ValueError("hypothesis IDs must be unique")
        if len({item.rank for item in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("hypothesis ranks must be unique")
        candidate_ids = {item.candidate_id for item in self.entity_candidates}
        if len(candidate_ids) != len(self.entity_candidates):
            raise ValueError("entity candidate IDs must be unique")
        for candidate in self.entity_candidates:
            for span in candidate.evidence:
                hypothesis = hypothesis_map.get(span.hypothesis_id)
                if hypothesis is None:
                    raise ValueError("entity evidence references an unknown hypothesis")
                if span.end_char > len(hypothesis.text):
                    raise ValueError("entity evidence exceeds its hypothesis")
                if hypothesis.text[span.start_char : span.end_char] != span.text:
                    raise ValueError("entity evidence text does not match its hypothesis span")
        return self


class SemanticStatusCode(IntEnum):
    ACCEPTED = 0
    CLARIFY = 1
    UNKNOWN = 2


class DialogueActCode(IntEnum):
    COMMAND = 0
    CORRECTION = 1
    CANCELLATION = 2
    CONFIRMATION = 3
    QUERY = 4
    STATUS = 5


class ClarificationCode(IntEnum):
    NONE = 0
    UNCLEAR_SPEECH = 1
    MISSING_TARGET = 2
    AMBIGUOUS_TARGET = 3
    MISSING_SCOPE = 4
    NO_PENDING_OPERATION = 5
    CONFLICTING_COMMANDS = 6


class SemanticPacket(Contract):
    """Compact grammar-constrained wire output produced by the semantic decoder."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    status: SemanticStatusCode = Field(alias="s")
    dialogue_act: DialogueActCode = Field(alias="a")
    intent_id: int | None = Field(default=None, alias="i", gt=0)
    slots: dict[str, int] = Field(default_factory=dict, alias="p", max_length=16)
    references: tuple[int, ...] = Field(default=(), alias="r", max_length=8)
    marker_bits: int = Field(default=0, alias="m", ge=0, le=15)
    clarification: ClarificationCode = Field(default=ClarificationCode.NONE, alias="q")

    def to_wire(self) -> dict[str, Any]:
        """Return only the compact model-facing keys in their fixed contract order."""

        return self.model_dump(mode="json", by_alias=True, exclude={"schema_version"})

    @field_validator("slots")
    @classmethod
    def validate_slots(cls, slots: dict[str, int]) -> dict[str, int]:
        if any(not name.strip() for name in slots):
            raise ValueError("slot names must be non-empty")
        if any(candidate_id <= 0 for candidate_id in slots.values()):
            raise ValueError("slot candidate IDs must be positive")
        return slots

    @field_validator("references")
    @classmethod
    def validate_references(cls, references: tuple[int, ...]) -> tuple[int, ...]:
        if any(reference_id <= 0 for reference_id in references):
            raise ValueError("reference IDs must be positive")
        if len(set(references)) != len(references):
            raise ValueError("reference IDs must be unique")
        return references

    @model_validator(mode="after")
    def validate_status(self) -> SemanticPacket:
        if self.status is SemanticStatusCode.ACCEPTED:
            if self.intent_id is None:
                raise ValueError("accepted semantic packet requires an intent ID")
            if self.clarification is not ClarificationCode.NONE:
                raise ValueError("accepted semantic packet cannot request clarification")
        else:
            if self.clarification is ClarificationCode.NONE:
                raise ValueError("non-accepted semantic packet requires a clarification reason")
        if self.status is SemanticStatusCode.UNKNOWN and (
            self.intent_id is not None or self.slots or self.references
        ):
            raise ValueError("unknown semantic packet cannot contain an interpretation")
        return self


class SemanticStatus(StrEnum):
    ACCEPTED = "accepted"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


class DialogueAct(StrEnum):
    COMMAND = "command"
    CORRECTION = "correction"
    CANCELLATION = "cancel"
    CONFIRMATION = "confirm"
    QUERY = "query"
    STATUS = "status"


class CriticalMarker(StrEnum):
    NEGATION = "negation"
    CORRECTION = "correction"
    CANCELLATION = "cancellation"
    AFFIRMATION = "affirmation"


class ClarificationReason(StrEnum):
    UNCLEAR_SPEECH = "unclear_speech"
    MISSING_TARGET = "missing_target"
    AMBIGUOUS_TARGET = "ambiguous_target"
    MISSING_SCOPE = "missing_scope"
    NO_PENDING_OPERATION = "no_pending_operation"
    CONFLICTING_COMMANDS = "conflicting_commands"


class DecoderSource(StrEnum):
    DETERMINISTIC = "deterministic"
    QWEN = "qwen"


class IntentEnvelope(Contract):
    """Validated semantic interpretation with explicitly zero execution authority."""

    session_id: UUID
    utterance_id: UUID
    emitted_monotonic_ns: int = Field(ge=0)
    status: SemanticStatus
    dialogue_act: DialogueAct | None = None
    intent: str | None = None
    slots: dict[str, str] = Field(default_factory=dict, max_length=16)
    slot_candidate_ids: dict[str, int] = Field(default_factory=dict, max_length=16)
    references: tuple[str, ...] = Field(default=(), max_length=8)
    critical_markers: frozenset[CriticalMarker] = Field(default_factory=frozenset)
    clarification_reason: ClarificationReason | None = None
    decoder_source: DecoderSource
    authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_semantics(self) -> IntentEnvelope:
        if set(self.slots) != set(self.slot_candidate_ids):
            raise ValueError("every slot must retain its evidence candidate ID")
        if self.status is SemanticStatus.ACCEPTED:
            if self.intent is None or self.dialogue_act is None:
                raise ValueError("accepted intent envelope requires act and intent")
            if self.clarification_reason is not None:
                raise ValueError("accepted intent envelope cannot request clarification")
        elif self.clarification_reason is None:
            raise ValueError("non-accepted intent envelope requires clarification reason")
        if self.status is SemanticStatus.UNKNOWN and (
            self.intent is not None
            or self.slots
            or self.references
            or self.dialogue_act is not None
        ):
            raise ValueError("unknown intent envelope cannot contain an interpretation")
        return self


class SynthesisRequest(Contract):
    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID | None = None
    text: NonEmpty
    voice_profile: NonEmpty
    language_hint: Literal["ta", "en", "mixed", "auto"] = "auto"
    data_classes: frozenset[DataClass] = Field(default_factory=frozenset)


class PlaybackEvent(Contract):
    request_id: UUID
    emitted_monotonic_ns: int = Field(ge=0)
    state: Literal["started", "progress", "ended", "cancelled", "failed"]
    played_ms: int = Field(ge=0)


class ActionIntent(Contract):
    task_id: UUID
    intent_id: UUID = Field(default_factory=uuid4)
    action: NonEmpty
    resource: NonEmpty
    purpose: NonEmpty
    destination: NonEmpty
    data_classes: frozenset[DataClass]
    reversible: bool
    expected_effect: dict[str, Any]
    verification: dict[str, Any]


class PolicyDecision(Contract):
    intent_id: UUID
    decision_id: UUID = Field(default_factory=uuid4)
    decided_at: datetime = Field(default_factory=utc_now)
    decision: Decision
    risk: RiskLevel
    reasons: tuple[str, ...]
    policy_bundle_version: NonEmpty


class Approval(Contract):
    intent_id: UUID
    approval_id: UUID = Field(default_factory=uuid4)
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    preview_digest: NonEmpty
    nonce: NonEmpty
    signature: NonEmpty

    @model_validator(mode="after")
    def validate_expiry(self) -> Approval:
        if self.expires_at <= self.issued_at:
            raise ValueError("approval must expire after issue time")
        return self


class CapabilityGrant(Contract):
    intent_id: UUID
    grant_id: UUID = Field(default_factory=uuid4)
    tool_id: NonEmpty
    action: NonEmpty
    resource: NonEmpty
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    max_uses: int = Field(default=1, ge=1, le=100)
    approval_id: UUID | None = None
    signature: NonEmpty

    @model_validator(mode="after")
    def validate_expiry(self) -> CapabilityGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("capability grant must expire after issue time")
        return self


class ToolResult(Contract):
    task_id: UUID
    intent_id: UUID
    grant_id: UUID
    tool_id: NonEmpty
    outcome: Outcome
    started_at: datetime
    finished_at: datetime
    summary: str
    output_digest: str | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> ToolResult:
        if self.finished_at < self.started_at:
            raise ValueError("tool result finish precedes start")
        return self


class Evidence(Contract):
    intent_id: UUID
    evidence_id: UUID = Field(default_factory=uuid4)
    observed_at: datetime = Field(default_factory=utc_now)
    predicate: NonEmpty
    outcome: Outcome
    source: NonEmpty
    digest: str | None = None


class AuditEvent(Contract):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID | None = None
    task_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    event_type: NonEmpty
    summary: str
    data_classes: frozenset[DataClass] = Field(default_factory=frozenset)
    previous_digest: str | None = None
    digest: NonEmpty


CONTRACT_TYPES: tuple[type[Contract], ...] = (
    Task,
    LLMMessage,
    ModelCapabilities,
    ProviderHealth,
    LLMRequest,
    LLMUsage,
    LLMResponse,
    ContextReference,
    ConversationTurn,
    TurnContext,
    ClarificationRequest,
    Assumption,
    PlanStepProposal,
    PlanProposal,
    MemoryProposal,
    InteractionEnvelope,
    PendingDialogue,
    ProviderProfile,
    GatewayConfig,
    SpeechSegment,
    LanguageSpan,
    TranscriptEvent,
    TranscriptHypothesis,
    EvidenceSpan,
    EntityCandidate,
    TranscriptEvidence,
    SemanticPacket,
    IntentEnvelope,
    SynthesisRequest,
    PlaybackEvent,
    ActionIntent,
    PolicyDecision,
    Approval,
    CapabilityGrant,
    ToolResult,
    Evidence,
    AuditEvent,
)
