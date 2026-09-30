"""Phase 5 Non-Destructive Plan Reconciler."""
from __future__ import annotations

from typing import Any, Optional
from slrag.contracts.events import ReconciliationEvent


class PlanReconciler:
    def __init__(self, bus: Optional[Any] = None, clock: Optional[Any] = None):
        self.bus = bus
        self.clock = clock

    def reconcile(
        self,
        ledger: Any,
        sub_intent_id: str,
        claim_text: str,
        is_update: bool = False,
        turn_id: str = "",
        reconciliation_type_override: Optional[str] = None
    ) -> str:
        rec_type = reconciliation_type_override or ("non_destructive_update" if is_update else "append")
        claim_id = ledger.add_or_update_claim(sub_intent_id, claim_text) if hasattr(ledger, "add_or_update_claim") else sub_intent_id

        if self.bus:
            ts = self.clock.time() if self.clock else None
            kw = {
                "turn_id": turn_id,
                "reconciliation_type": rec_type,
                "affected_claim_ids": [claim_id]
            }
            if ts is not None:
                kw["timestamp"] = ts
            self.bus.publish(ReconciliationEvent(**kw))
        return claim_id
