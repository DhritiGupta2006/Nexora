"""FastAPI server exposing /health, /ws/stream, /ws/telemetry, /metrics, and /debug/search."""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from slrag.config import AppConfig, DEFAULT_CONFIG
from slrag.contracts.events import (
    BaseEvent,
    TranscriptChunk,
    UtteranceEnd,
    AnswerDelta,
    Ledger,
    TurnSummary,
)
from slrag.gateway.session import SessionRegistry, GLOBAL_SESSION_REGISTRY
from slrag.retrieval.engine import HybridRetrievalEngine
from slrag.retrieval.instrumented import instrumented_search
from slrag.telemetry.bus import TelemetryBus, GLOBAL_BUS
from slrag.telemetry.metrics import MetricsCollector, GLOBAL_METRICS

logger = logging.getLogger(__name__)


class DebugSearchRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = 10
    session_id: str = "debug_session"


def create_app(
    config: AppConfig = DEFAULT_CONFIG,
    engine: Optional[HybridRetrievalEngine] = None,
    bus: Optional[TelemetryBus] = None,
    registry: Optional[SessionRegistry] = None,
    metrics: Optional[MetricsCollector] = None,
    turn_engine: Optional[Any] = None,
) -> FastAPI:
    """Create and configure the FastAPI application using modern lifespan handlers."""

    telemetry_bus = bus or GLOBAL_BUS
    session_reg = registry or GLOBAL_SESSION_REGISTRY
    retrieval_eng = engine or HybridRetrievalEngine(config)
    metrics_coll = metrics or GLOBAL_METRICS

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        telemetry_bus.start()
        await session_reg.start()
        yield
        await session_reg.stop()
        await telemetry_bus.close()

    app = FastAPI(
        title="SL-RAG Streaming Gateway & Telemetry Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.config = config
    app.state.engine = retrieval_eng
    app.state.bus = telemetry_bus
    app.state.registry = session_reg
    app.state.metrics = metrics_coll
    app.state.turn_engine = turn_engine
    app.state.start_time = time.time()

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        uptime = round(time.time() - app.state.start_time, 2)
        return {
            "status": "healthy",
            "uptime_seconds": uptime,
            "active_sessions": app.state.registry.active_sessions_count,
            "cfg_hash": app.state.config.cfg_hash,
            "indexed_chunks": len(app.state.engine.chunks_map),
        }

    @app.get("/metrics")
    async def get_metrics(format: str = Query("prometheus", pattern="^(prometheus|json)$")):
        """Metrics endpoint."""
        if format == "json":
            return app.state.metrics.get_snapshot().model_dump()
        return PlainTextResponse(app.state.metrics.get_prometheus_metrics())

    @app.post("/debug/search")
    async def debug_search(req: DebugSearchRequest):
        """Ad-hoc search debug endpoint."""
        if not app.state.engine.chunks_map:
            raise HTTPException(status_code=400, detail="Corpus index is empty.")

        turn_id = f"debug_turn_{int(time.time() * 1000)}"
        results = await instrumented_search(
            engine=app.state.engine,
            query=req.query,
            turn_id=turn_id,
            session_id=req.session_id,
            mode=req.mode,  # type: ignore
            top_k=req.top_k,
            bus=app.state.bus,
            metrics=app.state.metrics,
        )

        return {
            "query": req.query,
            "mode": req.mode,
            "top_k": req.top_k,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "score": r.score,
                    "rank": r.rank,
                    "section_title": r.section_title,
                    "doc_id": r.doc_id,
                    "text_preview": (r.text[:150] + "...") if len(r.text) > 150 else r.text,
                    "source_scores": r.source_scores,
                }
                for r in results
            ],
        }

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket):
        """Telemetry WebSocket subscription endpoint broadcasting all system events."""
        await websocket.accept()
        sub_queue = await app.state.bus.register_subscriber()
        try:
            while True:
                event = await sub_queue.get()
                await websocket.send_text(event.model_dump_json())
                sub_queue.task_done()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error in telemetry websocket: {e}")
        finally:
            await app.state.bus.unregister_subscriber(sub_queue)

    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket):
        """Bidirectional streaming gateway endpoint for user transcripts and answer deltas."""
        await websocket.accept()
        session_id = websocket.query_params.get("session_id", "ws_default_session")
        session_ctx = await app.state.registry.get_or_create(session_id)

        try:
            while True:
                msg_text = await websocket.receive_text()
                raw_data = json.loads(msg_text)
                
                # Normalize keys
                normalized = session_ctx.normalizer.normalize_dict_keys(raw_data)
                evt_type = normalized.get("event_type", "transcript_chunk")
                seq = int(normalized.get("seq", 0))

                if evt_type == "transcript_chunk":
                    chunk_evt = TranscriptChunk(
                        session_id=session_id,
                        seq=seq,
                        text=normalized.get("text", ""),
                        is_final=bool(normalized.get("is_final", False)),
                        speaker=normalized.get("speaker", "user"),
                        cfg_hash=app.state.config.cfg_hash,
                    )
                    # Pass through reorder buffer
                    ordered_events = session_ctx.reorder_buffer.push(chunk_evt)
                    for evt in ordered_events:
                        await app.state.bus.emit(evt)
                        app.state.metrics.record_event("transcript_chunk")

                elif evt_type == "utterance_end":
                    utt_evt = UtteranceEnd(
                        session_id=session_id,
                        seq=seq,
                        final_text=normalized.get("text", "") or normalized.get("final_text", ""),
                        turn_id=normalized.get("turn_id") or session_ctx.next_turn_id(),
                        cfg_hash=app.state.config.cfg_hash,
                    )
                    # Flush reorder buffer at utterance end
                    flushed = session_ctx.reorder_buffer.flush_all()
                    for evt in flushed:
                        await app.state.bus.emit(evt)

                    await app.state.bus.emit(utt_evt)
                    app.state.metrics.record_event("utterance_end")

                    # If turn_engine is attached, process turn end-to-end
                    if app.state.turn_engine:
                        async with session_ctx.lock:
                            async for out_evt in app.state.turn_engine.process_turn_stream(
                                session_ctx=session_ctx,
                                utterance=utt_evt.final_text,
                                turn_id=utt_evt.turn_id,
                            ):
                                await websocket.send_text(out_evt.model_dump_json())
                                await app.state.bus.emit(out_evt)
                                app.state.metrics.record_event(out_evt.event_type)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error in stream websocket: {e}", exc_info=True)

    return app
