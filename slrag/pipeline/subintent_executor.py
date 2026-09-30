"""Phase 5 Parallel Sub-Intent Retrieval Executor."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from slrag.contracts.events import SubIntentRetrievalEvent


class SubIntentExecutor:
    def __init__(self, retrieval_engine: Any, cache: Optional[Any] = None, bus: Optional[Any] = None, clock: Optional[Any] = None):
        self.retrieval_engine = retrieval_engine
        self.cache = cache
        self.bus = bus
        self.clock = clock

    async def execute_wave(
        self,
        wave: List[Dict[str, Any]],
        stage_idx: int,
        turn_id: str = "",
        expected_chunk_ids: Optional[List[str]] = None,
        sub_gold_map: Optional[Dict[str, List[str]]] = None
    ) -> Dict[str, List[Any]]:
        async def _fetch(sub: Dict[str, Any]):
            sub_id = sub["sub_intent_id"]
            text = sub["text"]
            chunks = None
            if self.cache:
                chunks = self.cache.get(text)
            if chunks is None:
                chunks = self.retrieval_engine.retrieve(text)
                if self.cache:
                    self.cache.put(text, chunks)

            retrieved_ids = [getattr(c, "id", str(i)) for i, c in enumerate(chunks)]

            if sub_gold_map and sub_id in sub_gold_map:
                sub_expected = sub_gold_map[sub_id]
            else:
                sub_expected = expected_chunk_ids or []

            if self.bus:
                ts = self.clock.time() if self.clock else None
                kw: Dict[str, Any] = {
                    "turn_id": turn_id,
                    "sub_intent_id": sub_id,
                    "retrieval_query": text,
                    "stage_idx": stage_idx,
                    "is_parallel": len(wave) > 1,
                    "retrieved_chunk_ids": retrieved_ids,
                    "expected_chunk_ids": sub_expected
                }
                if ts is not None:
                    kw["timestamp"] = ts
                self.bus.publish(SubIntentRetrievalEvent(**kw))
            return sub_id, chunks

        tasks = [_fetch(sub) for sub in wave]
        results = await asyncio.gather(*tasks)
        return dict(results)
