"""Frozen Pydantic v2 models for SL-RAG event contracts."""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from slrag.config import DEFAULT_CONFIG


def current_iso_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class BaseEvent(BaseModel):
    """Base event contract with frozen immutability and metadata."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str = Field(default_factory=generate_event_id)
    timestamp: str = Field(default_factory=current_iso_time)
    session_id: str = "default_session"
    seq: int = 0
    cfg_hash: str = Field(default_factory=lambda: DEFAULT_CONFIG.cfg_hash)
    event_type: str = "base_event"


class TranscriptChunk(BaseEvent):
    """Event representing an incremental speech-to-text transcript chunk."""
    event_type: Literal["transcript_chunk"] = "transcript_chunk"
    chunk_id: str = Field(default_factory=lambda: f"tc_{uuid.uuid4().hex[:8]}")
    text: str
    is_final: bool = False
    start_ms: int = 0
    end_ms: int = 0
    speaker: str = "user"


class UtteranceEnd(BaseEvent):
    """Event indicating end of user speech utterance."""
    event_type: Literal["utterance_end"] = "utterance_end"
    utterance_id: str = Field(default_factory=lambda: f"utt_{uuid.uuid4().hex[:8]}")
    final_text: str
    duration_ms: int = 0
    turn_id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")


class RetrievalItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    chunk_id: str
    score: float
    rank: int
    source_scores: Dict[str, Any] = Field(default_factory=dict)
    section_title: str = ""
    doc_id: str = ""


class RetrievalEvent(BaseEvent):
    """Event emitted during retrieval query execution."""
    event_type: Literal["retrieval"] = "retrieval"
    turn_id: str
    query: str
    mode: str
    top_k: int
    results: List[RetrievalItem]
    latency_ms: float


class SufficiencyCheckEvent(BaseEvent):
    """Event emitted during sufficiency gate evaluation."""
    event_type: Literal["sufficiency_check"] = "sufficiency_check"
    turn_id: str
    dense_top1_score: float
    coverage_score: float
    passed: bool
    reason: str


class ClaimStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str = Field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:8]}")
    text: str
    doc_ids: List[str] = Field(default_factory=list)  # Enum-constrained Doc IDs
    status: ClaimStatus = ClaimStatus.PENDING
    turn_id: str = ""


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str  # lexical, semantic, coreference, hallucinated_id, consistency
    passed: bool
    score: float = 1.0
    details: str = ""


class ClaimVerificationEvent(BaseEvent):
    """Event emitted when a claim undergoes 5-check fail-closed verification."""
    event_type: Literal["claim_verification"] = "claim_verification"
    turn_id: str
    claim_id: str
    claim_text: str
    doc_ids: List[str]
    checks: Dict[str, CheckResult]
    passed: bool
    rejection_reason: Optional[str] = None


class Ledger(BaseEvent):
    """Event snapshot of the verified claim ledger."""
    event_type: Literal["ledger_update"] = "ledger_update"
    ledger_version: int = 1
    verified_claims: List[Claim] = Field(default_factory=list)
    active_turn_id: str = ""


class AnswerDelta(BaseEvent):
    """Event streaming generated answer text delta to client."""
    event_type: Literal["answer_delta"] = "answer_delta"
    delta_id: str = Field(default_factory=lambda: f"dlta_{uuid.uuid4().hex[:8]}")
    turn_id: str
    text_delta: str
    is_final: bool = False


class TurnSummary(BaseEvent):
    """Event summarizing the end of a complete interaction turn."""
    event_type: Literal["turn_summary"] = "turn_summary"
    turn_id: str
    utterance: str
    claims_count: int
    verified_count: int
    rejected_count: int
    tokens_in: int
    tokens_out: int
    cost: float
    latency_ms: float
    status: str = "completed"


class MetricsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    total_events: int
    total_turns: int
    active_sessions: int
    p50_latency_ms: float
    p95_latency_ms: float
    events_by_type: Dict[str, int]
