"""Phase 4 Speculative Prefetch Cache with Deterministic Clock Injection."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from slrag.contracts.events import SpeculativeCacheEvent


class SpeculativeCache:
    def __init__(self, ttl_ms: int = 5000, max_size: int = 128, bus: Optional[Any] = None, clock: Optional[Any] = None):
        self.ttl_ms = ttl_ms
        self.max_size = max_size
        self.bus = bus
        self.clock = clock
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _now(self) -> float:
        return self.clock.time() if self.clock else time.time()

    def _normalize(self, query: str) -> str:
        return " ".join(query.strip().lower().split())

    def get(self, query: str) -> Optional[List[Any]]:
        self.cleanup_expired()
        norm_q = self._normalize(query)
        entry = self._cache.get(norm_q)
        if entry is None:
            for k, v in self._cache.items():
                if norm_q.startswith(k) or k.startswith(norm_q):
                    entry = v
                    break

        ts = self._now()
        if entry is not None:
            if self.bus:
                cids = [getattr(c, "id", str(i)) for i, c in enumerate(entry["chunks"])]
                self.bus.publish(SpeculativeCacheEvent(action="hit", query=query, chunk_ids=cids, timestamp=ts))
            return entry["chunks"]

        if self.bus:
            self.bus.publish(SpeculativeCacheEvent(action="miss", query=query, timestamp=ts))
        return None

    def put(self, query: str, chunks: List[Any]) -> None:
        self.cleanup_expired()
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["created_at"])
            del self._cache[oldest_key]

        norm_q = self._normalize(query)
        now = self._now()
        self._cache[norm_q] = {
            "chunks": chunks,
            "created_at": now
        }
        if self.bus:
            cids = [getattr(c, "id", str(i)) for i, c in enumerate(chunks)]
            self.bus.publish(SpeculativeCacheEvent(action="set", query=query, chunk_ids=cids, timestamp=now))

    def invalidate(self, query: Optional[str] = None) -> None:
        if query:
            norm_q = self._normalize(query)
            if norm_q in self._cache:
                del self._cache[norm_q]
        else:
            self._cache.clear()
        if self.bus:
            self.bus.publish(SpeculativeCacheEvent(action="invalidate", query=query or "*", timestamp=self._now()))

    def cleanup_expired(self) -> None:
        now = self._now()
        expired = [k for k, v in self._cache.items() if (now - v["created_at"]) * 1000.0 > self.ttl_ms]
        for k in expired:
            del self._cache[k]
