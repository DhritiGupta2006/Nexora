"""Instrumented search wrapper emitting retrieval telemetry events."""

import time
from typing import List, Literal, Optional

from slrag.contracts.events import RetrievalEvent, RetrievalItem
from slrag.retrieval.engine import HybridRetrievalEngine, SearchResult
from slrag.telemetry.bus import TelemetryBus, GLOBAL_BUS
from slrag.telemetry.metrics import MetricsCollector, GLOBAL_METRICS


async def instrumented_search(
    engine: HybridRetrievalEngine,
    query: str,
    turn_id: str,
    session_id: str = "default_session",
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid",
    top_k: int = 10,
    seq: int = 0,
    bus: Optional[TelemetryBus] = None,
    metrics: Optional[MetricsCollector] = None,
) -> List[SearchResult]:
    """Execute search while measuring latency, updating metrics, and emitting a RetrievalEvent."""
    telemetry_bus = bus or GLOBAL_BUS
    metrics_collector = metrics or GLOBAL_METRICS

    t0 = time.perf_counter()
    results = engine.search(query=query, mode=mode, top_k=top_k)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    retrieval_items = [
        RetrievalItem(
            chunk_id=r.chunk_id,
            score=float(r.score),
            rank=r.rank,
            source_scores=r.source_scores,
            section_title=r.section_title,
            doc_id=r.doc_id,
        )
        for r in results
    ]

    event = RetrievalEvent(
        session_id=session_id,
        turn_id=turn_id,
        seq=seq,
        query=query,
        mode=mode,
        top_k=top_k,
        results=retrieval_items,
        latency_ms=round(latency_ms, 3),
        cfg_hash=engine.config.cfg_hash,
    )

    await telemetry_bus.emit(event)
    metrics_collector.record_event("retrieval")
    metrics_collector.record_latency(latency_ms, kind="retrieval")

    return results
