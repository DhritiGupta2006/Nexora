"""Phase 5 Context Sufficiency Suppression and Uncertainty Handler."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from slrag.contracts.events import SubIntentCompletionEvent


class SuppressionController:
    def __init__(self, sufficiency_gate: Any, bus: Optional[Any] = None, clock: Optional[Any] = None):
        self.sufficiency_gate = sufficiency_gate
        self.bus = bus
        self.clock = clock

    def evaluate(
        self,
        sub_intent_id: str,
        sub_query: str,
        chunks: List[Any],
        turn_id: str = "",
        is_unanswerable_ground_truth: Optional[bool] = None
    ) -> Dict[str, Any]:
        ts = self.clock.time() if self.clock else None
        if not chunks:
            if self.bus:
                kw = {
                    "turn_id": turn_id,
                    "sub_intent_id": sub_intent_id,
                    "status": "suppressed",
                    "is_suppressed": True,
                    "is_uncertain": True,
                    "is_unanswerable_ground_truth": is_unanswerable_ground_truth
                }
                if ts is not None:
                    kw["timestamp"] = ts
                self.bus.publish(SubIntentCompletionEvent(**kw))
            return {
                "suppressed": True,
                "uncertain": True,
                "text": "Insufficient evidence: no relevant passages retrieved."
            }

        suff_result = self.sufficiency_gate.evaluate(sub_query, chunks)
        is_sufficient = getattr(suff_result, "sufficient", True)
        score = getattr(suff_result, "score", 1.0)
        reason = getattr(suff_result, "reason", "")

        if not is_sufficient:
            if self.bus:
                kw = {
                    "turn_id": turn_id,
                    "sub_intent_id": sub_intent_id,
                    "status": "suppressed",
                    "is_suppressed": True,
                    "is_uncertain": True,
                    "is_unanswerable_ground_truth": is_unanswerable_ground_truth
                }
                if ts is not None:
                    kw["timestamp"] = ts
                self.bus.publish(SubIntentCompletionEvent(**kw))
            return {
                "suppressed": True,
                "uncertain": True,
                "text": f"Suppressed due to insufficient context: {reason}"
            }

        is_uncertain = (0.50 <= score < 0.70)
        if self.bus:
            kw = {
                "turn_id": turn_id,
                "sub_intent_id": sub_intent_id,
                "status": "uncertain" if is_uncertain else "completed",
                "is_suppressed": False,
                "is_uncertain": is_uncertain,
                "is_unanswerable_ground_truth": is_unanswerable_ground_truth
            }
            if ts is not None:
                kw["timestamp"] = ts
            self.bus.publish(SubIntentCompletionEvent(**kw))

        return {
            "suppressed": False,
            "uncertain": is_uncertain,
            "text": ""
        }
