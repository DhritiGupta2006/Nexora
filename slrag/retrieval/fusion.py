"""Reciprocal Rank Fusion (RRF) for combining lexical (BM25) and semantic (Dense) rankings."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from slrag.config import RRFConfig, DEFAULT_CONFIG


@dataclass
class FusedResult:
    chunk_id: str
    rrf_score: float
    bm25_rank: Optional[int] = None
    bm25_score: Optional[float] = None
    dense_rank: Optional[int] = None
    dense_score: Optional[float] = None


def reciprocal_rank_fusion(
    bm25_results: List[Tuple[str, float]],
    dense_results: List[Tuple[str, float]],
    config: RRFConfig = DEFAULT_CONFIG.rrf,
    top_k: int = 10,
) -> List[FusedResult]:
    """Merge BM25 and Dense ranking lists using weighted Reciprocal Rank Fusion.
    
    Formula:
        Score(d) = w_bm25 / (k + rank_bm25(d)) + w_dense / (k + rank_dense(d))
    where rank is 1-indexed (1 for 1st item).
    """
    k = config.k
    w_bm25 = config.weight_bm25
    w_dense = config.weight_dense

    scores: Dict[str, float] = {}
    details: Dict[str, Dict[str, Any]] = {}

    # Process BM25 rankings
    for rank_0, (doc_id, bm25_score) in enumerate(bm25_results):
        rank = rank_0 + 1
        rrf_part = w_bm25 / (k + rank)
        scores[doc_id] = scores.get(doc_id, 0.0) + rrf_part
        if doc_id not in details:
            details[doc_id] = {}
        details[doc_id]["bm25_rank"] = rank
        details[doc_id]["bm25_score"] = bm25_score

    # Process Dense rankings
    for rank_0, (doc_id, dense_score) in enumerate(dense_results):
        rank = rank_0 + 1
        rrf_part = w_dense / (k + rank)
        scores[doc_id] = scores.get(doc_id, 0.0) + rrf_part
        if doc_id not in details:
            details[doc_id] = {}
        details[doc_id]["dense_rank"] = rank
        details[doc_id]["dense_score"] = dense_score

    # Deterministic sort: descending by score, tie-breaker ascending chunk_id
    sorted_items = sorted(scores.items(), key=lambda item: (-item[1], item[0]))

    fused_results: List[FusedResult] = []
    for doc_id, rrf_score in sorted_items[:top_k]:
        det = details.get(doc_id, {})
        fused_results.append(
            FusedResult(
                chunk_id=doc_id,
                rrf_score=float(rrf_score),
                bm25_rank=det.get("bm25_rank"),
                bm25_score=det.get("bm25_score"),
                dense_rank=det.get("dense_rank"),
                dense_score=det.get("dense_score"),
            )
        )

    return fused_results
