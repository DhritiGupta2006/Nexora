"""Tests for Phase 4 Cascade Controller and Speculative Cache."""
from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, List

from slrag.config import CascadeConfig, AppConfig, DEFAULT_CONFIG
from slrag.contracts.events import CascadeTriggerEvent, SpeculativeCacheEvent, SpeculationOutcomeEvent
from slrag.pipeline.cascade import CascadeController, CascadeState
from slrag.retrieval.cache import SpeculativeCache


class MockBus:
    def __init__(self):
        self.events: List[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class MockChunk:
    id: str
    text: str = ""


def test_cascade_trigger_lifecycle():
    bus = MockBus()
    config = CascadeConfig(
        confidence_threshold=0.70,
        entropy_threshold=0.40,
        min_token_boundary=4
    )
    controller = CascadeController(
        confidence_threshold=config.confidence_threshold,
        entropy_threshold=config.entropy_threshold,
        min_token_boundary=config.min_token_boundary,
        bus=bus
    )

    assert controller.state == CascadeState.IDLE
    res1 = controller.evaluate_token("What", "turn_1")
    assert res1["trigger"] is False
    assert controller.state == CascadeState.ACCUMULATING

    controller.evaluate_token(" is", "turn_1")
    controller.evaluate_token(" the", "turn_1")
    res4 = controller.evaluate_token(" architecture?", "turn_1")
    assert res4["trigger"] is True
    assert controller.state == CascadeState.SPECULATING

    controller.finalize_turn("What is the architecture?", "turn_1")
    assert controller.state == CascadeState.STABLE
    assert controller.speculation_used is True


def test_cascade_accumulating_state():
    bus = MockBus()
    config = CascadeConfig(min_token_boundary=5)
    controller = CascadeController(
        min_token_boundary=config.min_token_boundary,
        bus=bus
    )

    controller.evaluate_token("Hello", "turn_2")
    controller.evaluate_token(" world", "turn_2")
    assert controller.state == CascadeState.ACCUMULATING


def test_speculative_cache_hit_and_ttl():
    bus = MockBus()
    cache = SpeculativeCache(ttl_ms=5000, max_size=5, bus=bus)
    chunks = [MockChunk("c1"), MockChunk("c2")]

    cache.put("what is nexora", chunks)
    hit = cache.get("what is nexora")
    assert hit is not None
    assert len(hit) == 2

    hits = [e for e in bus.events if getattr(e, "action", "") == "hit"]
    assert len(hits) == 1


def test_speculative_cache_lru_eviction():
    cache = SpeculativeCache(ttl_ms=10000, max_size=2)
    cache.put("q1", [MockChunk("c1")])
    cache.put("q2", [MockChunk("c2")])
    cache.put("q3", [MockChunk("c3")])

    assert cache.get("q1") is None
    assert cache.get("q3") is not None


def test_speculative_cache_invalidation():
    cache = SpeculativeCache(ttl_ms=10000, max_size=5)
    cache.put("q1", [MockChunk("c1")])
    cache.invalidate("q1")
    assert cache.get("q1") is None


def test_speculation_outcome_used():
    bus = MockBus()
    config = CascadeConfig(min_token_boundary=2)
    controller = CascadeController(
        min_token_boundary=config.min_token_boundary,
        bus=bus
    )
    controller.evaluate_token("What is", "t1")
    controller.evaluate_token(" Nexora?", "t1")
    controller.finalize_turn("What is Nexora exactly?", "t1")

    outcomes = [e for e in bus.events if getattr(e, "outcome", "") == "used"]
    assert len(outcomes) == 1


def test_speculation_outcome_false_trigger():
    bus = MockBus()
    config = CascadeConfig(min_token_boundary=2)
    controller = CascadeController(
        min_token_boundary=config.min_token_boundary,
        bus=bus
    )
    controller.evaluate_token("What is", "t2")
    controller.evaluate_token(" Nexora?", "t2")
    controller.finalize_turn("Completely different divergent question?", "t2")

    outcomes = [e for e in bus.events if getattr(e, "outcome", "") == "invalidated"]
    assert len(outcomes) == 1


def test_cascade_bypass_when_disabled():
    cfg = CascadeConfig(enabled=False)
    assert cfg.enabled is False
    app_cfg = AppConfig(cascade=cfg)
    assert app_cfg.cascade.enabled is False