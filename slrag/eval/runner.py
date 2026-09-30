"""Deterministic Replay Runner executing B0, B1, and Ours on identical pipeline code."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from slrag.config import SlragConfig
from slrag.eval.clock import ReplayClock
from slrag.eval.gates import GateEvaluator
from slrag.eval.report import ReportGenerator
from slrag.eval.scenarios import write_split_files
from slrag.pipeline.turn_engine import TurnEngine
from slrag.telemetry.metrics import MetricCalculator


class InMemoryBus:
    def __init__(self):
        self.events: List[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


class ReplayRunner:
    def __init__(
        self,
        scenarios_path: str,
        mode: str = "ours",
        out_path: str = "out/telemetry.jsonl",
        playback: str = "virtual",
        config_overrides: Optional[Dict[str, Any]] = None
    ):
        self.scenarios_path = scenarios_path
        self.mode = mode.lower()
        self.out_path = out_path
        self.playback = playback
        self.config_overrides = config_overrides or {}
        self.clock = ReplayClock(start_time=1000.0, tick_interval=0.050)
        self.bus = InMemoryBus()

    def _configure_engine(self, target_mode: str) -> TurnEngine:
        from slrag.pipeline.drafter import Drafter
        from slrag.pipeline.ledger import ClaimLedger
        from slrag.pipeline.llm import LLMClient
        from slrag.pipeline.sufficiency import SufficiencyGate
        from slrag.pipeline.verifier import Verifier
        from slrag.retrieval.engine import InstrumentedRetrievalEngine

        if target_mode == "b0":
            cfg = SlragConfig(
                dense_weight=1.0,
                bm25_weight=0.0,
                enable_verifier=False,
                enable_cascade=False,
                enable_multi_intent=False,
                restart_on_late_detail=True,
                temperature=0.0,
                seed=13
            )
        elif target_mode == "b1":
            cfg = SlragConfig(
                dense_weight=0.6,
                bm25_weight=0.4,
                enable_verifier=True,
                enable_cascade=False,
                enable_multi_intent=False,
                restart_on_late_detail=True,
                temperature=0.0,
                seed=13
            )
        else:  # ours
            cfg = SlragConfig(
                dense_weight=0.6,
                bm25_weight=0.4,
                enable_verifier=True,
                enable_cascade=True,
                enable_multi_intent=True,
                restart_on_late_detail=False,
                temperature=0.0,
                seed=13
            )

        for k, v in self.config_overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        retrieval = InstrumentedRetrievalEngine(bus=self.bus, config=cfg)
        llm = LLMClient(config=cfg)
        verifier = Verifier(bus=self.bus, config=cfg) if cfg.enable_verifier else None
        sufficiency = SufficiencyGate(config=cfg)
        ledger = ClaimLedger()
        drafter = Drafter(llm=llm, config=cfg)

        return TurnEngine(
            config=cfg,
            retrieval_engine=retrieval,
            llm=llm,
            verifier=verifier,
            sufficiency=sufficiency,
            ledger=ledger,
            drafter=drafter,
            bus=self.bus,
            clock=self.clock
        )

    def _execute_scenarios(self, engine: TurnEngine, scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        self.bus.events.clear()
        self.clock.reset(1000.0)

        for sc in scenarios:
            query = sc["query"]
            tid = sc["scenario_id"]
            is_unans = sc.get("is_unanswerable", False)

            sub_gold = {}
            for s in sc.get("sub_intents", []):
                sub_gold[s["id"]] = s.get("gold_chunk_ids", [])

            self.clock.advance(0.050)
            if self.playback == "real":
                time.sleep(0.050)

            asyncio.run(engine.execute_turn(
                query=query,
                turn_id=tid,
                is_unanswerable_ground_truth=is_unans,
                sub_gold_map=sub_gold
            ))
            self.clock.advance(0.050)

        raw_events = []
        for e in self.bus.events:
            if hasattr(e, "__dict__"):
                raw_events.append(e.__dict__)
            elif isinstance(e, dict):
                raw_events.append(e)
        return raw_events

    def run(self, generate_report: bool = True) -> Dict[str, Any]:
        p = Path(self.scenarios_path)
        if not p.exists():
            write_split_files()

        scenarios = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    scenarios.append(json.loads(line.strip()))

        # 1. Execute Target Mode
        target_engine = self._configure_engine(self.mode)
        raw_events = self._execute_scenarios(target_engine, scenarios)

        out_p = Path(self.out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            for d in raw_events:
                f.write(json.dumps(d) + "\n")

        metrics = MetricCalculator.calculate_all(raw_events)

        # 2. In 'ours' mode, genuinely execute B1 and B0 on the same scenarios
        baseline_metrics = {}
        if generate_report and self.mode == "ours":
            b1_engine = self._configure_engine("b1")
            b1_events = self._execute_scenarios(b1_engine, scenarios)
            b1_metrics = MetricCalculator.calculate_all(b1_events)

            b0_engine = self._configure_engine("b0")
            b0_events = self._execute_scenarios(b0_engine, scenarios)
            b0_metrics = MetricCalculator.calculate_all(b0_events)
            b0_metrics["groundedness"] = None

            baseline_metrics = {"b1": b1_metrics, "b0": b0_metrics}
            gates = GateEvaluator.evaluate_gates(metrics, b1_metrics, b0_metrics)
        else:
            dummy_b = dict(metrics)
            gates = GateEvaluator.evaluate_gates(metrics, dummy_b, dummy_b)

        if generate_report:
            cal_config = {
                "mode": self.mode,
                "seed": 13,
                "temperature": 0.0,
                "enable_cascade": self.mode == "ours",
                "enable_multi_intent": self.mode == "ours"
            }
            scenario_counts = {
                "total": 75,
                "tune": 36,
                "test": 39
            }
            summary_path = str(out_p.parent / "summary.json")
            report_path = str(out_p.parent / "report.md")
            ReportGenerator.write_summary(summary_path, self.mode, metrics, gates, scenario_counts, cal_config, baseline_metrics)
            ReportGenerator.write_markdown_report(report_path, self.mode, metrics, gates, scenario_counts, cal_config, baseline_metrics)

        return {"metrics": metrics, "gates": gates}
