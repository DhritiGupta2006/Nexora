"""Global configuration and configuration hashing for SL-RAG."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Dict


@dataclass(frozen=True)
class ChunkerConfig:
    min_tokens: int = 300
    max_tokens: int = 500
    overlap_tokens: int = 50
    approx_chars_per_token: float = 4.0


@dataclass(frozen=True)
class BM25Config:
    k1: float = 1.5
    b: float = 0.75
    epsilon: float = 0.25


@dataclass(frozen=True)
class DenseConfig:
    model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    normalize_embeddings: bool = True
    batch_size: int = 32


@dataclass(frozen=True)
class RRFConfig:
    k: int = 60
    weight_bm25: float = 0.5
    weight_dense: float = 0.5


@dataclass(frozen=True)
class SufficiencyConfig:
    dense_top1_threshold: float = 0.55
    coverage_threshold: float = 0.50


@dataclass(frozen=True)
class VerifierConfig:
    lexical_threshold: float = 0.30
    semantic_threshold: float = 0.65
    coreference_check_enabled: bool = True
    hallucinated_id_check_enabled: bool = True
    consistency_check_enabled: bool = True


@dataclass(frozen=True)
class LLMConfig:
    model_name: str = "Qwen/Qwen2.5-3B-Instruct"
    cost_per_1k_input: float = 0.00015
    cost_per_1k_output: float = 0.00060
    temperature: float = 0.1
    max_tokens: int = 512


@dataclass(frozen=True)
class TelemetryConfig:
    jsonl_log_path: str = "telemetry.jsonl"
    buffer_size: int = 20000
    drain_timeout_sec: float = 5.0


@dataclass(frozen=True)
class SessionConfig:
    idle_timeout_seconds: float = 1800.0
    cleanup_interval_seconds: float = 60.0


@dataclass(frozen=True)
class CascadeConfig:
    enabled: bool = True
    confidence_threshold: float = 0.72
    entropy_threshold: float = 0.38
    min_token_boundary: int = 4
    cache_ttl_ms: int = 5000
    cache_max_size: int = 128


@dataclass(frozen=True)
class MultiIntentConfig:
    enabled: bool = True
    suppression_threshold: float = 0.45
    enable_parallel_retrieval: bool = True
    restart_on_late_detail: bool = False


@dataclass(frozen=True)
class AppConfig:
    chunker: ChunkerConfig = field(default_factory=ChunkerConfig)
    bm25: BM25Config = field(default_factory=BM25Config)
    dense: DenseConfig = field(default_factory=DenseConfig)
    rrf: RRFConfig = field(default_factory=RRFConfig)
    sufficiency: SufficiencyConfig = field(default_factory=SufficiencyConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    cascade: CascadeConfig = field(default_factory=CascadeConfig)
    multi_intent: MultiIntentConfig = field(default_factory=MultiIntentConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def cfg_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Default singleton instance
DEFAULT_CONFIG = AppConfig()