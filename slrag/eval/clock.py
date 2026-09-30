"""Deterministic Replay Virtual Clock."""
from __future__ import annotations

from typing import Optional


class ReplayClock:
    def __init__(self, start_time: float = 1000.0, tick_interval: float = 0.050):
        self._current_time = start_time
        self._tick_interval = tick_interval

    def time(self) -> float:
        return self._current_time

    def advance(self, delta: Optional[float] = None) -> float:
        d = self._tick_interval if delta is None else delta
        self._current_time += d
        return self._current_time

    def reset(self, start_time: float = 1000.0) -> None:
        self._current_time = start_time
