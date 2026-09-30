"""Hyperparameter calibration sweep targeting strictly the tune split."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from slrag.eval.runner import ReplayRunner
from slrag.eval.scenarios import write_split_files


class CalibrationSweep:
    @staticmethod
    def run_sweep(tune_scenarios_path: str = "eval/scenarios/tune.jsonl") -> Dict[str, Any]:
        p = Path(tune_scenarios_path)
        if "test" in str(p).lower():
            raise ValueError("Test scenarios must NEVER be used for calibration.")

        if not p.exists():
            write_split_files()

        # Calibration grid sweep over controller and sufficiency thresholds using existing SlragConfig fields.
        # Note: The existing Verifier in Phase 3 evaluates groundedness deterministically without a configurable threshold.
        candidates = [
            {"cascade_confidence_threshold": 0.65, "cascade_entropy_threshold": 0.45, "sufficiency_threshold": 0.60},
            {"cascade_confidence_threshold": 0.70, "cascade_entropy_threshold": 0.40, "sufficiency_threshold": 0.65},
            {"cascade_confidence_threshold": 0.72, "cascade_entropy_threshold": 0.38, "sufficiency_threshold": 0.65},
            {"cascade_confidence_threshold": 0.80, "cascade_entropy_threshold": 0.30, "sufficiency_threshold": 0.70},
        ]

        best_score = -1.0
        best_cfg = candidates[2]

        for cand in candidates:
            runner = ReplayRunner(
                scenarios_path=str(p),
                mode="ours",
                out_path="out/tune_telemetry.jsonl",
                playback="virtual",
                config_overrides=cand
            )
            res = runner.run(generate_report=False)
            metrics = res["metrics"]
            score = (metrics.get("sub_intent_recall") or 0.0) - (metrics.get("wasted_speculation_rate") or 0.0)
            if score > best_score:
                best_score = score
                best_cfg = cand

        final_calibrated = {
            "seed": 13,
            "temperature": 0.0,
            "cascade_confidence_threshold": best_cfg["cascade_confidence_threshold"],
            "cascade_entropy_threshold": best_cfg["cascade_entropy_threshold"],
            "min_token_boundary": 4,
            "sufficiency_threshold": best_cfg["sufficiency_threshold"],
            "suppression_threshold": 0.45,
            "enable_verifier": True,
            "enable_cascade": True,
            "enable_multi_intent": True
        }

        cal_out = Path("out/calibrated_config.json")
        cal_out.parent.mkdir(parents=True, exist_ok=True)
        with open(cal_out, "w", encoding="utf-8") as f:
            json.dump(final_calibrated, f, indent=2)

        return final_calibrated
