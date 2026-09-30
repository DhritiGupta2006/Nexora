"""Phase 5 DAG Dependency Planner."""
from __future__ import annotations

from typing import Any, Dict, List


class DAGPlanner:
    @staticmethod
    def plan(sub_intents: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        if not sub_intents:
            return []

        waves: List[List[Dict[str, Any]]] = []
        resolved_ids = set()
        remaining = list(sub_intents)

        while remaining:
            current_wave = []
            for item in remaining:
                deps = set(item.get("depends_on", []))
                if deps.issubset(resolved_ids):
                    current_wave.append(item)

            if not current_wave:
                current_wave = remaining[:]
                remaining = []
            else:
                for item in current_wave:
                    remaining.remove(item)
                    resolved_ids.add(item["sub_intent_id"])
            waves.append(current_wave)

        return waves
