"""Phase 5 Multi-Intent Decomposition and Context Injection."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from slrag.contracts.events import SubIntentDecompositionEvent


class IntentDecomposer:
    def __init__(self, bus: Optional[Any] = None, clock: Optional[Any] = None):
        self.bus = bus
        self.clock = clock

    def decompose(self, query: str, turn_id: str = "") -> List[Dict[str, Any]]:
        cleaned = query.strip()
        conjunctive_patterns = [r"\s+and\s+", r"\s+while\s+", r"\s+as well as\s+", r";", r"\.\s+"]

        splits = [cleaned]
        for pattern in conjunctive_patterns:
            new_splits = []
            for part in splits:
                parts = re.split(pattern, part, flags=re.IGNORECASE)
                new_splits.extend([p.strip() for p in parts if p.strip()])
            splits = new_splits

        is_compound = len(splits) > 1
        sub_intents = []

        primary_subject = ""
        words = splits[0].split()
        if len(words) > 2:
            primary_subject = " ".join(words[1:3])

        for idx, part in enumerate(splits):
            sub_id = f"sub_{idx + 1}"
            resolved_query = part
            if idx > 0 and primary_subject and not any(w in part.lower() for w in primary_subject.lower().split()):
                resolved_query = f"{part} (regarding {primary_subject})"

            sub_intents.append({
                "sub_intent_id": sub_id,
                "text": resolved_query,
                "depends_on": [] if idx == 0 else [f"sub_{idx}"] if "then" in part.lower() else []
            })

        if self.bus:
            ts = self.clock.time() if self.clock else None
            kw: Dict[str, Any] = {
                "turn_id": turn_id,
                "query": query,
                "sub_intents": sub_intents,
                "is_compound": is_compound
            }
            if ts is not None:
                kw["timestamp"] = ts
            self.bus.publish(SubIntentDecompositionEvent(**kw))

        return sub_intents
