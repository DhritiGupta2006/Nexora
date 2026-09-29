"""Sequence ordering reorder buffer for handling out-of-order stream packets."""

from collections import deque
import logging
import time
from typing import Dict, List, Optional
from slrag.contracts.events import BaseEvent

logger = logging.getLogger(__name__)


class ReorderBuffer:
    """Reorder buffer ensuring strict monotonic sequence ordering."""

    def __init__(self, initial_seq: int = 0, gap_timeout_sec: float = 2.0, max_buffer_size: int = 500):
        self.expected_seq = initial_seq
        self.gap_timeout_sec = gap_timeout_sec
        self.max_buffer_size = max_buffer_size
        self._buffer: Dict[int, BaseEvent] = {}  # seq -> event
        self._last_arrival_time = time.time()
        self._initialized = False

    def push(self, event: BaseEvent) -> List[BaseEvent]:
        """Push an event and return a list of in-order events ready for immediate processing."""
        self._last_arrival_time = time.time()
        seq = event.seq

        # Auto-initialize expected_seq with first event's seq if not initialized
        if not self._initialized:
            self.expected_seq = seq
            self._initialized = True

        # Duplicate or late packet
        if seq < self.expected_seq:
            logger.debug(f"Late or duplicate event discarded: seq={seq}, expected={self.expected_seq}")
            return []

        # Buffer the event
        self._buffer[seq] = event

        # Drain contiguous sequence
        ready_events: List[BaseEvent] = []
        while self.expected_seq in self._buffer:
            ready_events.append(self._buffer.pop(self.expected_seq))
            self.expected_seq += 1

        # Check if buffer is growing too large (e.g. dropped packet) -> force drain lowest seq
        if len(self._buffer) >= self.max_buffer_size:
            ready_events.extend(self._force_drain_lowest())

        return ready_events

    def check_timeout(self) -> List[BaseEvent]:
        """Force drain if missing packets timed out."""
        if self._buffer and (time.time() - self._last_arrival_time > self.gap_timeout_sec):
            return self._force_drain_lowest()
        return []

    def _force_drain_lowest(self) -> List[BaseEvent]:
        """Force progress by advancing expected_seq to the lowest buffered sequence."""
        if not self._buffer:
            return []
        min_seq = min(self._buffer.keys())
        self.expected_seq = min_seq
        ready = []
        while self.expected_seq in self._buffer:
            ready.append(self._buffer.pop(self.expected_seq))
            self.expected_seq += 1
        return ready

    def flush_all(self) -> List[BaseEvent]:
        """Flush all remaining buffered events in sorted order."""
        sorted_seqs = sorted(self._buffer.keys())
        events = [self._buffer.pop(s) for s in sorted_seqs]
        if sorted_seqs:
            self.expected_seq = sorted_seqs[-1] + 1
        return events
