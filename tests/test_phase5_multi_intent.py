"""Tests for Phase 5 Multi-Intent Pipeline and TurnEngine Integration."""
from __future__ import annotations

import asyncio
import pytest
from dataclasses import dataclass
from typing import Any, List

from slrag.config import SlragConfig
from slrag.contracts.events import (
    SubIntentDecompositionEvent,
    SubIntentRetrievalEvent,
    SubIntentCompletionEvent,
    ReconciliationEvent,
    MultiIntentResolutionEvent,
    VerificationEvent,
    FirstTokenEmissionEvent,
)
from slrag.pipeline.dag_planner import DAGPlanner
from slrag.pipeline.intent_decomposer import IntentDecomposer
from slrag.pipeline.ledger import ClaimLedger
from slrag.pipeline.reconciler import PlanReconciler
from slrag.pipeline.subintent_executor import SubIntentExecutor
from slrag.pipeline.suppression import SuppressionController
from slrag.pipeline.turn_engine import TurnEngine
from slrag.retrieval.cache import SpeculativeCache
from slrag.telemetry.metrics import MetricCalculator, calculate_percentile


class MockBus:
    def __init__(self):
        self.events: List[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class MockChunk:
    id: str
    text: str
    score: float = 0.85


class MockRetrievalEngine:
    def __init__(self):
        self.queries_called: List[str] = []

    def retrieve(self, query: str) -> List[MockChunk]:
        self.queries_called.append(query)
        return [
            MockChunk(id="c1", text=f"Evidence 1 for {query}", score=0.90),
            MockChunk(id="c2", text=f"Evidence 2 for {query}", score=0.85),
        ]


@dataclass
class MockSufficiencyResult:
    sufficient: bool
    score: float
    reason: str = ""


class MockSufficiencyGate:
    def __init__(self, sufficient: bool = True, score: float = 0.85):
        self.sufficient = sufficient
        self.score = score

    def evaluate(self, query: str, chunks: List[Any]) -> MockSufficiencyResult:
        if not chunks:
            return MockSufficiencyResult(sufficient=False, score=0.0, reason="No chunks")
        return MockSufficiencyResult(
            sufficient=self.sufficient,
            score=self.score,
            reason="Sufficiency verified" if self.sufficient else "Lacks key aspect"
        )


@dataclass
class MockVerificationResult:
    grounded: bool
    groundedness_score: float


class MockVerifier:
    def __init__(self, bus: Any = None):
        self.bus = bus

    def verify(self, draft: str, chunks: List[Any], turn_id: str = "") -> MockVerificationResult:
        res = MockVerificationResult(grounded=True, groundedness_score=0.95)
        if self.bus:
            self.bus.publish(VerificationEvent(
                turn_id=turn_id,
                grounded=res.grounded,
                groundedness_score=res.groundedness_score
            ))
        return res


class MockDrafter:
    def draft(self, query: str, chunks: List[Any], temperature: float = 0.0, seed: int = 13) -> str:
        return f"Synthesized answer for '{query}' using {len(chunks)} sources."


class MockLLM:
    def generate(self, prompt: str, temperature: float = 0.0, seed: int = 13) -> str:
        return f"LLM generation: {prompt[:30]}"


def test_compound_query_decomposition():
    bus = MockBus()
    decomposer = IntentDecomposer(bus=bus)
    query = "What is Nexora and how does it compare to standard RAG?"
    sub_intents = decomposer.decompose(query, turn_id="t1")

    assert len(sub_intents) == 2
    assert sub_intents[0]["sub_intent_id"] == "sub_1"
    assert sub_intents[1]["sub_intent_id"] == "sub_2"
    decomp_events = [e for e in bus.events if isinstance(e, SubIntentDecompositionEvent)]
    assert len(decomp_events) == 1
    assert decomp_events[0].is_compound is True


def test_single_intent_passthrough():
    bus = MockBus()
    decomposer = IntentDecomposer(bus=bus)
    query = "What is the dense index dimension?"
    sub_intents = decomposer.decompose(query, turn_id="t2")

    assert len(sub_intents) == 1
    assert sub_intents[0]["sub_intent_id"] == "sub_1"
    decomp_events = [e for e in bus.events if isinstance(e, SubIntentDecompositionEvent)]
    assert len(decomp_events) == 1
    assert decomp_events[0].is_compound is False


def test_slot_context_propagation():
    decomposer = IntentDecomposer()
    query = "What is BM25 and why is it faster?"
    sub_intents = decomposer.decompose(query, turn_id="t3")

    assert len(sub_intents) == 2
    assert "BM25" in sub_intents[1]["text"] or "regarding" in sub_intents[1]["text"].lower()


def test_independent_dag_waves():
    planner = DAGPlanner()
    intents = [
        {"sub_intent_id": "sub_1", "text": "Q1", "depends_on": []},
        {"sub_intent_id": "sub_2", "text": "Q2", "depends_on": []},
    ]
    waves = planner.plan(intents)
    assert len(waves) == 1
    assert len(waves[0]) == 2


def test_dependent_dag_waves():
    planner = DAGPlanner()
    intents = [
        {"sub_intent_id": "sub_1", "text": "Q1", "depends_on": []},
        {"sub_intent_id": "sub_2", "text": "Q2", "depends_on": ["sub_1"]},
    ]
    waves = planner.plan(intents)
    assert len(waves) == 2
    assert waves[0][0]["sub_intent_id"] == "sub_1"
    assert waves[1][0]["sub_intent_id"] == "sub_2"


@pytest.mark.asyncio
async def test_parallel_retrieval_execution():
    bus = MockBus()
    engine = MockRetrievalEngine()
    executor = SubIntentExecutor(retrieval_engine=engine, cache=None, bus=bus)
    wave = [
        {"sub_intent_id": "sub_1", "text": "Query A"},
        {"sub_intent_id": "sub_2", "text": "Query B"},
    ]
    results = await executor.execute_wave(wave, stage_idx=0, turn_id="t6")

    assert "sub_1" in results
    assert "sub_2" in results
    assert len(engine.queries_called) == 2
    retrieval_events = [e for e in bus.events if isinstance(e, SubIntentRetrievalEvent)]
    assert len(retrieval_events) == 2
    assert all(e.is_parallel for e in retrieval_events)


@pytest.mark.asyncio
async def test_speculative_cache_reuse():
    bus = MockBus()
    engine = MockRetrievalEngine()
    cache = SpeculativeCache(ttl_ms=5000, max_size=10, bus=bus)
    cached_chunks = [MockChunk(id="cached_1", text="Cached data", score=0.99)]
    cache.put("Cached Query", cached_chunks)

    executor = SubIntentExecutor(retrieval_engine=engine, cache=cache, bus=bus)
    wave = [{"sub_intent_id": "sub_1", "text": "Cached Query"}]
    results = await executor.execute_wave(wave, stage_idx=0, turn_id="t7")

    assert results["sub_1"][0].id == "cached_1"
    assert len(engine.queries_called) == 0


def test_sufficiency_suppression():
    bus = MockBus()
    gate = MockSufficiencyGate(sufficient=False, score=0.30)
    controller = SuppressionController(sufficiency_gate=gate, bus=bus)

    res = controller.evaluate(
        sub_intent_id="sub_1",
        sub_query="Unanswerable query",
        chunks=[MockChunk(id="c1", text="Irrelevant", score=0.30)],
        turn_id="t8",
        is_unanswerable_ground_truth=True
    )
    assert res["suppressed"] is True
    assert "Suppressed" in res["text"]
    comp_events = [e for e in bus.events if isinstance(e, SubIntentCompletionEvent)]
    assert len(comp_events) == 1
    assert comp_events[0].status == "suppressed"
    assert comp_events[0].is_suppressed is True


def test_uncertainty_handling():
    bus = MockBus()
    gate = MockSufficiencyGate(sufficient=True, score=0.60)
    controller = SuppressionController(sufficiency_gate=gate, bus=bus)

    res = controller.evaluate(
        sub_intent_id="sub_1",
        sub_query="Marginal query",
        chunks=[MockChunk(id="c1", text="Marginal context", score=0.60)],
        turn_id="t9",
        is_unanswerable_ground_truth=False
    )
    assert res["suppressed"] is False
    assert res["uncertain"] is True
    comp_events = [e for e in bus.events if isinstance(e, SubIntentCompletionEvent)]
    assert len(comp_events) == 1
    assert comp_events[0].status == "uncertain"
    assert comp_events[0].is_uncertain is True


def test_non_destructive_reconciliation():
    bus = MockBus()
    ledger = ClaimLedger()
    reconciler = PlanReconciler(bus=bus)

    c1 = reconciler.reconcile(ledger, "sub_1", "Initial statement.", is_update=False, turn_id="t10")
    c2 = reconciler.reconcile(ledger, "sub_1", "Refined statement.", is_update=True, turn_id="t10")

    rec_events = [e for e in bus.events if isinstance(e, ReconciliationEvent)]
    assert len(rec_events) == 2
    assert rec_events[0].reconciliation_type == "append"
    assert rec_events[1].reconciliation_type == "non_destructive_update"


@pytest.mark.asyncio
async def test_configuration_toggle_disables_multi_intent():
    bus = MockBus()
    config = SlragConfig(enable_multi_intent=False, enable_cascade=False)
    engine = MockRetrievalEngine()
    turn_engine = TurnEngine(
        config=config,
        retrieval_engine=engine,
        llm=MockLLM(),
        verifier=MockVerifier(bus=bus),
        sufficiency=MockSufficiencyGate(sufficient=True, score=0.9),
        ledger=ClaimLedger(),
        drafter=MockDrafter(),
        bus=bus
    )

    res = await turn_engine.execute_turn("Query A and Query B", turn_id="t11")
    assert "Synthesized answer" in res["output"]
    decomp_events = [e for e in bus.events if isinstance(e, SubIntentDecompositionEvent)]
    assert len(decomp_events) == 0


def test_telemetry_completeness_and_percentiles():
    events = [
        {"event_type": "turn_start", "turn_id": "t1", "timestamp": 100.0},
        {"event_type": "first_token_emission", "turn_id": "t1", "timestamp": 100.030},
        {"event_type": "turn_start", "turn_id": "t2", "timestamp": 200.0},
        {"event_type": "first_token_emission", "turn_id": "t2", "timestamp": 200.048},
        {"event_type": "speculative_cache", "action": "hit"},
        {"event_type": "speculative_cache", "action": "miss"},
        {"event_type": "speculation_outcome", "outcome": "wasted"},
        {"event_type": "speculative_retrieval", "is_early": True},
        {"event_type": "sub_intent_completion", "is_suppressed": True, "is_uncertain": True, "is_unanswerable_ground_truth": True},
        {"event_type": "multi_intent_resolution", "total_sub_intents": 2, "resolved_count": 2},
    ]
    metrics = MetricCalculator.calculate_all(events)

    assert pytest.approx(metrics["ttft_p50"], 0.1) == 39.0
    assert metrics["cache_hit_rate"] == 0.5
    assert metrics["wasted_speculation_rate"] == 1.0
    assert metrics["early_retrieval_rate"] == 1.0
    assert metrics["sub_intent_recall"] == 1.0
    assert metrics["suppression_precision"] == 1.0
    assert metrics["suppression_recall"] == 1.0


@pytest.mark.asyncio
async def test_real_turn_engine_orchestration():
    bus = MockBus()
    config = SlragConfig(
        enable_multi_intent=True,
        enable_cascade=True,
        enable_verifier=True,
        temperature=0.0,
        seed=13
    )
    turn_engine = TurnEngine(
        config=config,
        retrieval_engine=MockRetrievalEngine(),
        llm=MockLLM(),
        verifier=MockVerifier(bus=bus),
        sufficiency=MockSufficiencyGate(sufficient=True, score=0.88),
        ledger=ClaimLedger(),
        drafter=MockDrafter(),
        bus=bus
    )

    result = await turn_engine.execute_turn(
        query="What is the architecture and how is it tested?",
        turn_id="t13"
    )

    assert result["resolved_count"] == 2
    assert result["suppressed_count"] == 0
    assert "Synthesized answer" in result["output"]

    event_types = [e.event_type for e in bus.events]
    assert "turn_start" in event_types
    assert "sub_intent_decomposition" in event_types
    assert "sub_intent_retrieval" in event_types
    assert "sub_intent_completion" in event_types
    assert "reconciliation" in event_types
    assert "multi_intent_resolution" in event_types
    assert "turn_complete" in event_types


def test_subintent_completion_event_dataclass_fields():
    event = SubIntentCompletionEvent(
        turn_id="t14",
        sub_intent_id="sub_1",
        status="suppressed",
        is_suppressed=True,
        is_uncertain=True,
        is_unanswerable_ground_truth=True
    )
    assert event.is_suppressed is True
    assert event.is_uncertain is True
    assert event.is_unanswerable_ground_truth is True


@pytest.mark.asyncio
async def test_subintent_executor_expected_chunk_ids_propagation():
    bus = MockBus()
    engine = MockRetrievalEngine()
    executor = SubIntentExecutor(retrieval_engine=engine, cache=None, bus=bus)
    wave = [{"sub_intent_id": "sub_1", "text": "Testing retrieval"}]
    expected = ["c1", "c2"]

    await executor.execute_wave(wave, stage_idx=0, turn_id="t15", expected_chunk_ids=expected)

    retrieval_events = [e for e in bus.events if isinstance(e, SubIntentRetrievalEvent)]
    assert len(retrieval_events) == 1
    assert retrieval_events[0].expected_chunk_ids == ["c1", "c2"]
    assert retrieval_events[0].retrieved_chunk_ids == ["c1", "c2"]


@pytest.mark.asyncio
async def test_verification_telemetry_emission_no_duplicates():
    bus = MockBus()
    config = SlragConfig(enable_multi_intent=False, enable_verifier=True)
    turn_engine = TurnEngine(
        config=config,
        retrieval_engine=MockRetrievalEngine(),
        llm=MockLLM(),
        verifier=MockVerifier(bus=bus),
        sufficiency=MockSufficiencyGate(sufficient=True, score=0.9),
        ledger=ClaimLedger(),
        drafter=MockDrafter(),
        bus=bus
    )

    await turn_engine.execute_turn("Query verification", turn_id="t16")
    v_events = [e for e in bus.events if isinstance(e, VerificationEvent)]
    assert len(v_events) == 1
    assert v_events[0].groundedness_score == 0.95


def test_concrete_telemetry_recall_at_5_and_10():
    events = [
        {
            "event_type": "sub_intent_retrieval",
            "turn_id": "t17",
            "retrieved_chunk_ids": ["c1", "c2", "c3", "c4", "c5", "c6"],
            "expected_chunk_ids": ["c1", "c6"]
        }
    ]
    metrics = MetricCalculator.calculate_all(events)
    assert metrics["recall@5"] == 0.5
    assert metrics["recall@10"] == 1.0


def test_early_retrieval_and_speculative_metrics():
    events = [
        {"event_type": "speculative_retrieval", "turn_id": "t18", "is_early": True},
        {"event_type": "speculative_retrieval", "turn_id": "t18", "is_early": False},
        {"event_type": "speculation_outcome", "turn_id": "t18", "outcome": "wasted"},
        {"event_type": "speculation_outcome", "turn_id": "t18", "outcome": "false_trigger"},
    ]
    metrics = MetricCalculator.calculate_all(events)
    assert metrics["early_retrieval_rate"] == 0.5
    assert metrics["wasted_speculation_rate"] == 0.5
    assert metrics["false_trigger_rate"] == 0.5


def test_per_turn_trace_coverage():
    turn_a_events = [
        {"event_type": "turn_start", "turn_id": "turn_a"},
        {"event_type": "sub_intent_retrieval", "turn_id": "turn_a"},
        {"event_type": "sub_intent_completion", "turn_id": "turn_a"},
        {"event_type": "first_token_emission", "turn_id": "turn_a"},
        {"event_type": "verification", "turn_id": "turn_a"},
        {"event_type": "turn_complete", "turn_id": "turn_a"},
    ]
    metrics_a = MetricCalculator.calculate_all(turn_a_events)
    assert metrics_a["trace_coverage"] == 1.0

    turn_b_events = [
        {"event_type": "turn_start", "turn_id": "turn_b"},
        {"event_type": "sub_intent_retrieval", "turn_id": "turn_b"},
        {"event_type": "sub_intent_completion", "turn_id": "turn_b"},
        {"event_type": "first_token_emission", "turn_id": "turn_b"},
        {"event_type": "turn_complete", "turn_id": "turn_b"},
    ]
    metrics_b = MetricCalculator.calculate_all(turn_b_events)
    assert pytest.approx(metrics_b["trace_coverage"], 0.01) == (5.0 / 6.0)

    combined = MetricCalculator.calculate_all(turn_a_events + turn_b_events)
    assert pytest.approx(combined["trace_coverage"], 0.01) == ((1.0 + 5.0 / 6.0) / 2.0)


def test_deterministic_percentile_linear():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    p50 = calculate_percentile(values, 0.50)
    p95 = calculate_percentile(values, 0.95)
    assert p50 == 30.0
    assert p95 == 48.0
