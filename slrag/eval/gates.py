"""Evaluation of G1-G6 gates with strict threshold enforcement."""
from __future__ import annotations

from typing import Any, Dict


class GateEvaluator:
    @staticmethod
    def evaluate_gates(
        ours_metrics: Dict[str, Any],
        b1_metrics: Dict[str, Any],
        b0_metrics: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        ours_r10 = ours_metrics.get("recall@10") or 0.0
        b1_r10 = b1_metrics.get("recall@10") or 0.0
        g1_pass = (ours_r10 >= b1_r10)

        ours_ground = ours_metrics.get("groundedness") or 0.0
        b1_ground = b1_metrics.get("groundedness") or 0.0
        g3_pass = (ours_ground >= b1_ground)

        return {
            "G1_recall_improvement": {
                "metric": "recall@10",
                "condition": "Ours >= B1",
                "ours": ours_r10,
                "b1": b1_r10,
                "status": "PASS" if g1_pass else "FAIL"
            },
            "G2_latency_ttft": {
                "metric": "ttft_p50",
                "condition": "UNSPECIFIED",
                "ours": ours_metrics.get("ttft_p50"),
                "b1": b1_metrics.get("ttft_p50"),
                "status": "UNSPECIFIED"
            },
            "G3_groundedness_preservation": {
                "metric": "groundedness",
                "condition": "Ours >= B1",
                "ours": ours_ground,
                "b1": b1_ground,
                "status": "PASS" if g3_pass else "FAIL"
            },
            "G4_multi_intent_resolution": {
                "metric": "sub_intent_recall",
                "condition": "UNSPECIFIED",
                "ours": ours_metrics.get("sub_intent_recall"),
                "status": "UNSPECIFIED"
            },
            "G5_speculative_efficiency": {
                "metric": "wasted_speculation_rate",
                "condition": "UNSPECIFIED",
                "ours": ours_metrics.get("wasted_speculation_rate"),
                "status": "UNSPECIFIED"
            },
            "G6_suppression_uncertainty": {
                "metric": "suppression_precision",
                "condition": "UNSPECIFIED",
                "ours": ours_metrics.get("suppression_precision"),
                "status": "UNSPECIFIED"
            }
        }
