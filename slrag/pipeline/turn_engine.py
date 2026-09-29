"""Batch Turn Engine coordinating retrieval, sufficiency gate, claim drafting, verification, and streaming."""

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from slrag.config import AppConfig, DEFAULT_CONFIG
from slrag.contracts.events import (
    AnswerDelta,
    BaseEvent,
    Claim,
    ClaimStatus,
    Ledger,
    TurnSummary,
)
from slrag.gateway.session import SessionContext
from slrag.pipeline.drafter import ClaimDrafter
from slrag.pipeline.ledger import ClaimLedger
from slrag.pipeline.llm import LLMServiceWrapper
from slrag.pipeline.sufficiency import SufficiencyGate
from slrag.pipeline.verifier import FailClosedVerifier
from slrag.retrieval.engine import HybridRetrievalEngine
from slrag.retrieval.instrumented import instrumented_search
from slrag.telemetry.bus import TelemetryBus, GLOBAL_BUS
from slrag.telemetry.metrics import MetricsCollector, GLOBAL_METRICS

logger = logging.getLogger(__name__)


class BatchTurnEngine:
    """End-to-end turn orchestrator executing retrieval, sufficiency, generation, verification, and streaming."""

    def __init__(
        self,
        config: AppConfig = DEFAULT_CONFIG,
        engine: Optional[HybridRetrievalEngine] = None,
        bus: Optional[TelemetryBus] = None,
        metrics: Optional[MetricsCollector] = None,
    ):
        self.config = config
        self.engine = engine or HybridRetrievalEngine(config)
        self.bus = bus or GLOBAL_BUS
        self.metrics = metrics or GLOBAL_METRICS

        self.llm_service = LLMServiceWrapper(config.llm)
        self.sufficiency_gate = SufficiencyGate(config.sufficiency)
        self.verifier = FailClosedVerifier(config.verifier)

    def _get_or_init_session_ledger(self, session_ctx: SessionContext) -> ClaimLedger:
        """Retrieve or initialize the session-scoped claim ledger."""
        if "ledger" not in session_ctx.custom_state:
            session_ctx.custom_state["ledger"] = ClaimLedger(session_ctx.session_id)
        return session_ctx.custom_state["ledger"]

    async def process_turn_stream(
        self,
        session_ctx: SessionContext,
        utterance: str,
        turn_id: str,
    ) -> AsyncIterator[BaseEvent]:
        """Execute a complete interaction turn and yield output stream events."""
        t_start = time.perf_counter()
        session_id = session_ctx.session_id
        ledger = self._get_or_init_session_ledger(session_ctx)
        seq = 100

        # 1. Hybrid Retrieval with instrumentation
        retrieval_results = await instrumented_search(
            engine=self.engine,
            query=utterance,
            turn_id=turn_id,
            session_id=session_id,
            mode="hybrid",
            top_k=5,
            seq=seq,
            bus=self.bus,
            metrics=self.metrics,
        )
        seq += 1

        # 2. Sufficiency Gate
        passed_sufficiency, dense_score, coverage_score, reason = await self.sufficiency_gate.evaluate_and_emit(
            query=utterance,
            results=retrieval_results,
            turn_id=turn_id,
            session_id=session_id,
            seq=seq,
            bus=self.bus,
        )
        seq += 1

        if not passed_sufficiency:
            # Fallback for insufficient knowledge
            fallback_msg = "I do not have enough context in the knowledge base to answer this question accurately."
            delta_evt = AnswerDelta(
                session_id=session_id,
                turn_id=turn_id,
                seq=seq,
                text_delta=fallback_msg,
                is_final=True,
            )
            seq += 1
            await self.bus.emit(delta_evt)
            yield delta_evt

            latency_ms = (time.perf_counter() - t_start) * 1000.0
            turn_summary = TurnSummary(
                session_id=session_id,
                turn_id=turn_id,
                seq=seq,
                utterance=utterance,
                claims_count=0,
                verified_count=0,
                rejected_count=0,
                tokens_in=self.llm_service.estimate_tokens(utterance),
                tokens_out=self.llm_service.estimate_tokens(fallback_msg),
                cost=0.0,
                latency_ms=round(latency_ms, 2),
                status="insufficient_context",
            )
            yield turn_summary
            self.metrics.record_turn()
            self.metrics.record_latency(latency_ms, kind="turn")
            return

        # 3. LLM Generation & Claim Drafting
        retrieved_chunks_map = {r.chunk_id: self.engine.chunks_map[r.chunk_id] for r in retrieval_results if r.chunk_id in self.engine.chunks_map}
        allowed_doc_ids: Set[str] = set(retrieved_chunks_map.keys())

        chunks_payload = [
            {"chunk_id": r.chunk_id, "text": r.text, "section_title": r.section_title}
            for r in retrieval_results
        ]
        llm_result = await self.llm_service.generate_grounded_response(
            query=utterance,
            retrieved_chunks=chunks_payload,
        )

        drafter = ClaimDrafter(allowed_doc_ids=allowed_doc_ids)
        drafted_claims = drafter.draft_from_raw_claims(llm_result.raw_claims, turn_id=turn_id)

        # 4. Fail-Closed Verification on every claim
        verified_claims: List[Claim] = []
        rejected_claims: List[Claim] = []
        previously_verified = ledger.get_verified_claims()

        for claim in drafted_claims:
            updated_claim, passed = await self.verifier.verify_and_emit(
                claim=claim,
                retrieved_chunks_map=retrieved_chunks_map,
                allowed_doc_ids=allowed_doc_ids,
                previously_verified=previously_verified,
                turn_id=turn_id,
                session_id=session_id,
                seq=seq,
                bus=self.bus,
            )
            seq += 1
            if passed:
                verified_claims.append(updated_claim)
            else:
                rejected_claims.append(updated_claim)

        # 5. Update Claim Ledger with verified claims
        if verified_claims:
            ledger.add_verified_claims(verified_claims, turn_id=turn_id)
        
        ledger_snapshot = await ledger.emit_snapshot(turn_id=turn_id, seq=seq, bus=self.bus)
        seq += 1

        # 6. Stream AnswerDelta containing ONLY verified claims
        if verified_claims:
            answer_parts = [f"{c.text} [{', '.join(c.doc_ids)}]" for c in verified_claims]
            verified_answer_text = " ".join(answer_parts)
        else:
            verified_answer_text = "I could not verify any facts to answer your query with confidence."

        # Emit in chunks to simulate streaming deltas
        words = verified_answer_text.split()
        chunk_size = max(1, len(words) // 3)
        for i in range(0, len(words), chunk_size):
            chunk_words = words[i:i + chunk_size]
            delta_str = " ".join(chunk_words)
            if i > 0:
                delta_str = " " + delta_str
            is_final = (i + chunk_size >= len(words))

            delta_evt = AnswerDelta(
                session_id=session_id,
                turn_id=turn_id,
                seq=seq,
                text_delta=delta_str,
                is_final=is_final,
            )
            seq += 1
            await self.bus.emit(delta_evt)
            yield delta_evt
            await asyncio.sleep(0.01)  # Micro-yield for stream simulation

        # Yield ledger update
        yield ledger_snapshot

        # 7. Emit Turn Summary
        latency_ms = (time.perf_counter() - t_start) * 1000.0
        turn_summary = TurnSummary(
            session_id=session_id,
            turn_id=turn_id,
            seq=seq,
            utterance=utterance,
            claims_count=len(drafted_claims),
            verified_count=len(verified_claims),
            rejected_count=len(rejected_claims),
            tokens_in=llm_result.tokens_in,
            tokens_out=llm_result.tokens_out,
            cost=llm_result.cost,
            latency_ms=round(latency_ms, 2),
            status="completed",
        )
        await self.bus.emit(turn_summary)
        self.metrics.record_turn()
        self.metrics.record_latency(latency_ms, kind="turn")

        yield turn_summary
