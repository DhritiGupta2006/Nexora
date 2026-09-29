"""Unit and integration tests for Phase 2: Contracts, Telemetry Bus 10k burst, Gateway, and Sessions."""

import asyncio
import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from slrag.config import AppConfig, SessionConfig, TelemetryConfig, DEFAULT_CONFIG
from slrag.contracts.events import (
    BaseEvent,
    TranscriptChunk,
    UtteranceEnd,
    RetrievalEvent,
    SufficiencyCheckEvent,
    ClaimVerificationEvent,
    Ledger,
    AnswerDelta,
    TurnSummary,
)
from slrag.corpus.loader import CorpusLoader
from slrag.gateway.normalizer import EventNormalizer
from slrag.gateway.reorder_buffer import ReorderBuffer
from slrag.gateway.session import SessionRegistry
from slrag.retrieval.engine import HybridRetrievalEngine
from slrag.retrieval.instrumented import instrumented_search
from slrag.server.app import create_app
from slrag.telemetry.bus import TelemetryBus
from slrag.telemetry.metrics import MetricsCollector
from slrag.telemetry.trace import TraceCoverageChecker

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_corpus.json"


@pytest.mark.anyio
async def test_10k_burst_telemetry_zero_loss(tmp_path):
    """Emit 10,000 events in a rapid burst and verify zero loss in JSONL and subscriber."""
    log_file = tmp_path / "burst_telemetry.jsonl"
    cfg = TelemetryConfig(jsonl_log_path=str(log_file), buffer_size=25000)
    bus = TelemetryBus(cfg)
    bus.start()

    # Register mock WebSocket subscriber queue
    subscriber_queue = await bus.register_subscriber(maxsize=25000)

    NUM_EVENTS = 10000
    sent_event_ids = []

    for i in range(NUM_EVENTS):
        evt = TranscriptChunk(
            session_id="burst_session",
            seq=i,
            text=f"Streaming speech packet payload index {i}",
            is_final=(i == NUM_EVENTS - 1),
            cfg_hash=DEFAULT_CONFIG.cfg_hash,
        )
        sent_event_ids.append(evt.event_id)
        await bus.emit(evt)

    # Wait for queue to drain
    await bus.drain()
    await bus.close()

    # Verify JSONL lines
    assert log_file.exists()
    with open(log_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == NUM_EVENTS

    # Verify subscriber received all events
    received_events = []
    while not subscriber_queue.empty():
        received_events.append(subscriber_queue.get_nowait())

    assert len(received_events) == NUM_EVENTS

    # Verify event ID parity and cfg_hash presence
    json_event_ids = [json.loads(line)["event_id"] for line in lines]
    sub_event_ids = [e.event_id for e in received_events]

    assert json_event_ids == sent_event_ids
    assert sub_event_ids == sent_event_ids
    assert all(json.loads(line).get("cfg_hash") == DEFAULT_CONFIG.cfg_hash for line in lines)


@pytest.mark.anyio
async def test_session_isolation_and_locks():
    """Verify state isolation across sessions and per-session lock concurrency."""
    registry = SessionRegistry()
    await registry.start()

    s1 = await registry.get_or_create("session_alpha")
    s2 = await registry.get_or_create("session_beta")

    assert s1.session_id != s2.session_id
    assert s1.lock is not s2.lock

    # Session mutations
    s1.custom_state["user"] = "Alice"
    s2.custom_state["user"] = "Bob"

    assert s1.custom_state["user"] == "Alice"
    assert s2.custom_state["user"] == "Bob"
    assert registry.active_sessions_count == 2

    await registry.stop()


def test_gateway_normalizer_and_reorder_buffer():
    """Test schema normalization, cumulative/delta speech text, and reorder buffer."""
    normalizer = EventNormalizer()

    # Test key alias normalization
    raw_payload = {"transcript": "hello world", "seq_no": "5", "isFinal": True}
    norm_dict = normalizer.normalize_dict_keys(raw_payload)
    assert norm_dict["text"] == "hello world"
    assert norm_dict["seq"] == 5
    assert norm_dict["is_final"] is True

    # Test cumulative text merging
    d1, full1 = normalizer.process_transcript_text("quantum", is_cumulative=True)
    assert d1 == "quantum"
    assert full1 == "quantum"

    d2, full2 = normalizer.process_transcript_text("quantum computing", is_cumulative=True)
    assert d2 == "computing"
    assert full2 == "quantum computing"

    reset_full = normalizer.reset_utterance()
    assert reset_full == "quantum computing"

    # Test ReorderBuffer
    rb = ReorderBuffer(initial_seq=1)
    e1 = TranscriptChunk(seq=1, text="one")
    e2 = TranscriptChunk(seq=2, text="two")
    e3 = TranscriptChunk(seq=3, text="three")
    e4 = TranscriptChunk(seq=4, text="four")

    # Push out of order: 1, 3, 4, then 2
    r1 = rb.push(e1)
    assert len(r1) == 1 and r1[0].seq == 1

    r3 = rb.push(e3)
    assert len(r3) == 0  # Buffering seq 3

    r4 = rb.push(e4)
    assert len(r4) == 0  # Buffering seq 4

    r2 = rb.push(e2)
    # Now seq 2, 3, 4 should all be released in sequence!
    assert len(r2) == 3
    assert [e.seq for e in r2] == [2, 3, 4]


def test_trace_coverage_checker():
    """Verify trace coverage validation for turns."""
    turn_id = "turn_test_101"
    session_id = "sess_01"

    valid_trace = [
        TranscriptChunk(session_id=session_id, turn_id=turn_id, seq=1, text="how does raft work"),
        UtteranceEnd(session_id=session_id, turn_id=turn_id, seq=2, final_text="how does raft work"),
        RetrievalEvent(session_id=session_id, turn_id=turn_id, seq=3, query="raft", mode="hybrid", top_k=2, results=[], latency_ms=1.2),
        SufficiencyCheckEvent(session_id=session_id, turn_id=turn_id, seq=4, dense_top1_score=0.85, coverage_score=0.9, passed=True, reason="Sufficient"),
        ClaimVerificationEvent(session_id=session_id, turn_id=turn_id, seq=5, claim_id="c1", claim_text="Raft has leader", doc_ids=["DOC002§raft_consensus"], checks={}, passed=True),
        AnswerDelta(session_id=session_id, turn_id=turn_id, seq=6, text_delta="Raft uses leader election.", is_final=True),
        Ledger(session_id=session_id, active_turn_id=turn_id, seq=7, ledger_version=1),
        TurnSummary(session_id=session_id, turn_id=turn_id, seq=8, utterance="how does raft work", claims_count=1, verified_count=1, rejected_count=0, tokens_in=50, tokens_out=20, cost=0.0001, latency_ms=15.0),
    ]

    res = TraceCoverageChecker.validate_turn_trace(valid_trace, turn_id=turn_id)
    assert res.is_valid is True
    assert len(res.missing_events) == 0

    # Incomplete trace
    incomplete_trace = valid_trace[:3]
    bad_res = TraceCoverageChecker.validate_turn_trace(incomplete_trace, turn_id=turn_id)
    assert bad_res.is_valid is False
    assert len(bad_res.missing_events) > 0


@pytest.mark.anyio
async def test_fastapi_server_endpoints(tmp_path):
    """Verify FastAPI /health, /metrics, and /debug/search endpoints."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    engine.index_documents(docs)

    log_file = tmp_path / "server_telemetry.jsonl"
    bus = TelemetryBus(TelemetryConfig(jsonl_log_path=str(log_file)))
    metrics = MetricsCollector()
    registry = SessionRegistry()

    app = create_app(
        config=DEFAULT_CONFIG,
        engine=engine,
        bus=bus,
        registry=registry,
        metrics=metrics,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Health check
        h_resp = await client.get("/health")
        assert h_resp.status_code == 200
        h_json = h_resp.json()
        assert h_json["status"] == "healthy"
        assert h_json["cfg_hash"] == DEFAULT_CONFIG.cfg_hash
        assert h_json["indexed_chunks"] == 8

        # 2. Debug search
        s_resp = await client.post(
            "/debug/search",
            json={"query": "Raft leader election", "mode": "hybrid", "top_k": 3},
        )
        assert s_resp.status_code == 200
        s_json = s_resp.json()
        assert len(s_json["results"]) == 3
        assert s_json["results"][0]["chunk_id"] == "DOC002§raft_consensus"

        # 3. Metrics endpoint
        m_json_resp = await client.get("/metrics?format=json")
        assert m_json_resp.status_code == 200
        m_data = m_json_resp.json()
        assert m_data["total_events"] >= 1

        m_prom_resp = await client.get("/metrics?format=prometheus")
        assert m_prom_resp.status_code == 200
        assert "slrag_events_total" in m_prom_resp.text


def test_websocket_stream_and_telemetry(tmp_path):
    """Verify bidirectional streaming over /ws/stream and event broadcast over /ws/telemetry."""
    from starlette.testclient import TestClient
    from slrag.pipeline.turn_engine import BatchTurnEngine

    docs = CorpusLoader.load_file(CORPUS_PATH)
    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    engine.index_documents(docs)

    log_file = tmp_path / "ws_telemetry.jsonl"
    bus = TelemetryBus(TelemetryConfig(jsonl_log_path=str(log_file)))
    metrics = MetricsCollector()
    registry = SessionRegistry()
    turn_engine = BatchTurnEngine(DEFAULT_CONFIG, engine=engine, bus=bus, metrics=metrics)

    app = create_app(
        config=DEFAULT_CONFIG,
        engine=engine,
        bus=bus,
        registry=registry,
        metrics=metrics,
        turn_engine=turn_engine,
    )

    with TestClient(app) as client:
        # Connect to telemetry WebSocket
        with client.websocket_connect("/ws/telemetry") as ws_telemetry:
            # Connect to stream WebSocket
            with client.websocket_connect("/ws/stream?session_id=ws_test_user") as ws_stream:
                # Send transcript chunk
                ws_stream.send_text(json.dumps({
                    "event_type": "transcript_chunk",
                    "text": "What is Raft consensus?",
                    "seq": 1,
                }))

                # Send utterance end
                ws_stream.send_text(json.dumps({
                    "event_type": "utterance_end",
                    "text": "What is Raft consensus?",
                    "seq": 2,
                }))

                # Receive streamed response deltas from ws_stream
                received_stream_deltas = []
                while True:
                    data = json.loads(ws_stream.receive_text())
                    received_stream_deltas.append(data)
                    if data.get("event_type") == "turn_summary":
                        break

                assert len(received_stream_deltas) >= 3
                assert any(d.get("event_type") == "answer_delta" for d in received_stream_deltas)
                assert any(d.get("event_type") == "ledger_update" for d in received_stream_deltas)

            # Check that telemetry WebSocket also received events
            tel_evt = json.loads(ws_telemetry.receive_text())
            assert "event_id" in tel_evt
            assert "cfg_hash" in tel_evt

