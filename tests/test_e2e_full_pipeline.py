"""End-to-end integration test connecting Phase 1, Phase 2, and Phase 3."""

import asyncio
import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from slrag.config import AppConfig, DEFAULT_CONFIG
from slrag.contracts.events import BaseEvent, TranscriptChunk, UtteranceEnd
from slrag.corpus.loader import CorpusLoader
from slrag.gateway.session import SessionRegistry
from slrag.pipeline.turn_engine import BatchTurnEngine
from slrag.retrieval.engine import HybridRetrievalEngine
from slrag.server.app import create_app
from slrag.telemetry.bus import TelemetryBus
from slrag.telemetry.metrics import MetricsCollector
from slrag.telemetry.trace import TraceCoverageChecker

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_corpus.json"


@pytest.mark.anyio
async def test_full_e2e_streaming_turn(tmp_path):
    """Full End-to-End System Test:
    1. Load and Index corpus.
    2. Start TelemetryBus and SessionRegistry.
    3. Execute turn via BatchTurnEngine.
    4. Verify telemetry logs in JSONL.
    5. Verify trace coverage compliance.
    6. Verify metrics counters and percentiles.
    """
    # 1. Ingest and index corpus
    docs = CorpusLoader.load_file(CORPUS_PATH)
    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    indexed_count = engine.index_documents(docs)
    assert indexed_count == 8

    # 2. Setup Telemetry & Gateway
    log_file = tmp_path / "e2e_telemetry.jsonl"
    bus = TelemetryBus(DEFAULT_CONFIG.telemetry.__class__(jsonl_log_path=str(log_file)))
    bus.start()
    metrics = MetricsCollector()
    registry = SessionRegistry(metrics=metrics)
    await registry.start()

    turn_engine = BatchTurnEngine(
        config=DEFAULT_CONFIG,
        engine=engine,
        bus=bus,
        metrics=metrics,
    )

    # 3. Simulate client session
    session_ctx = await registry.get_or_create("e2e_user_session_01")
    turn_id = session_ctx.next_turn_id()

    # Client sends transcript chunks
    chunks = [
        TranscriptChunk(session_id=session_ctx.session_id, turn_id=turn_id, seq=1, text="How does"),
        TranscriptChunk(session_id=session_ctx.session_id, turn_id=turn_id, seq=2, text="the surface code protect physical qubits?"),
    ]
    for c in chunks:
        ordered = session_ctx.reorder_buffer.push(c)
        for e in ordered:
            await bus.emit(e)

    utt_end = UtteranceEnd(
        session_id=session_ctx.session_id,
        turn_id=turn_id,
        seq=3,
        final_text="How does the surface code protect physical qubits?",
    )
    await bus.emit(utt_end)

    # 4. Process turn through pipeline
    turn_events: list[BaseEvent] = []
    async with session_ctx.lock:
        async for evt in turn_engine.process_turn_stream(
            session_ctx=session_ctx,
            utterance=utt_end.final_text,
            turn_id=turn_id,
        ):
            turn_events.append(evt)

    # Wait for telemetry to drain
    await bus.drain()
    await registry.stop()
    await bus.close()

    # 5. Verify Turn Events
    event_types = [e.event_type for e in turn_events]
    assert "answer_delta" in event_types
    assert "ledger_update" in event_types
    assert "turn_summary" in event_types

    # 6. Verify Telemetry JSONL file
    assert log_file.exists()
    with open(log_file, "r", encoding="utf-8") as f:
        log_lines = [json.loads(line) for line in f if line.strip()]

    assert len(log_lines) >= 7
    all_logged_types = [entry["event_type"] for entry in log_lines]
    assert "retrieval" in all_logged_types
    assert "sufficiency_check" in all_logged_types
    assert "claim_verification" in all_logged_types
    assert "turn_summary" in all_logged_types

    # 7. Trace Coverage Validation
    all_turn_events = chunks + [utt_end] + turn_events
    # Also include internal emitted events (retrieval, sufficiency, verification)
    trace_res = TraceCoverageChecker.validate_turn_trace(
        [BaseEvent.model_validate(entry) if "event_type" in entry else entry for entry in log_lines],
        turn_id=turn_id,
    )
    assert trace_res.is_valid is True
    assert trace_res.turn_type == "sufficient"

    # 8. Check Metrics
    snap = metrics.get_snapshot()
    assert snap.total_turns == 1
    assert snap.total_events > 0
    assert snap.p50_latency_ms >= 0.0
