"""Summary.json and Markdown report exporter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class ReportGenerator:
    @staticmethod
    def write_summary(
        summary_path: str,
        mode: str,
        metrics: Dict[str, Any],
        gates: Dict[str, Any],
        scenario_counts: Dict[str, int],
        calibration_config: Dict[str, Any],
        baseline_metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        p = Path(summary_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mode": mode,
            "scenario_counts": scenario_counts,
            "calibration_config": calibration_config,
            "metrics": metrics,
            "gates": gates,
            "baseline_metrics": baseline_metrics or {}
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def write_markdown_report(
        report_path: str,
        mode: str,
        metrics: Dict[str, Any],
        gates: Dict[str, Any],
        scenario_counts: Dict[str, int],
        calibration_config: Dict[str, Any],
        baseline_metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Nexora Phase 6 Evaluation Report: Mode `{mode}`",
            "",
            "## 1. Scenario Dataset Summary",
            f"- **Tune Scenarios (Frozen Seed 13):** {scenario_counts.get('tune', 36)}",
            f"- **Test Scenarios (Frozen Seed 13):** {scenario_counts.get('test', 39)}",
            f"- **Total Authored Scenarios:** {scenario_counts.get('total', 75)}",
            "",
            "## 2. Replay Clock & Timing Semantics",
            "- **Evaluation Clock:** Deterministic virtual replay clock (50 ms tick interval).",
            "- **Wall-Clock Pacing:** Optional 1x real-time terminal sleep pacing; metric calculations use deterministic logical time.",
            "",
            "## 3. Calibrated Configuration",
            "```json",
            json.dumps(calibration_config, indent=2),
            "```",
            "",
            "## 4. Telemetry Metrics Summary",
            "| Metric | Value |",
            "| :--- | :--- |",
        ]
        for k, v in sorted(metrics.items()):
            val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
            lines.append(f"| `{k}` | {val_str} |")

        lines.extend([
            "",
            "## 5. Acceptance Gates (G1–G6)",
            "| Gate | Metric | Condition | Status | Detail |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for g_id, g_info in sorted(gates.items()):
            m = g_info.get("metric", "")
            cond = g_info.get("condition", "")
            st = g_info.get("status", "")
            detail = f"Ours={g_info.get('ours')} vs B1={g_info.get('b1')}" if "b1" in g_info else ""
            lines.append(f"| **{g_id}** | `{m}` | {cond} | **{st}** | {detail} |")

        lines.append("")
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
