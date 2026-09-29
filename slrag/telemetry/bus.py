"""Zero-loss Telemetry Bus dispatching events to JSONL file and WebSocket subscribers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel

from slrag.config import TelemetryConfig, DEFAULT_CONFIG
from slrag.contracts.events import BaseEvent

logger = logging.getLogger(__name__)


class TelemetryBus:
    """Async event bus guaranteeing zero loss under high-throughput burst conditions."""

    def __init__(self, config: TelemetryConfig = DEFAULT_CONFIG.telemetry):
        self.config = config
        self.log_path = Path(config.jsonl_log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory subscriber queues (for WebSockets)
        self._subscribers: Set[asyncio.Queue] = set()
        self._subscribers_lock = asyncio.Lock()
        
        # Internal async event processing queue
        self._event_queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=config.buffer_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._file_handle = None
        self._total_emitted = 0
        self._total_written = 0

    def start(self):
        """Start the background consumer worker."""
        if not self._running:
            self._running = True
            # Open file in append mode with line buffering
            self._file_handle = open(self.log_path, "a", encoding="utf-8", buffering=1)
            self._worker_task = asyncio.create_task(self._process_queue())

    async def emit(self, event: BaseEvent):
        """Enqueue an event for telemetry emission."""
        if not self._running:
            self.start()
        self._total_emitted += 1
        await self._event_queue.put(event)

    def emit_nowait(self, event: BaseEvent):
        """Non-blocking emit for sync contexts or fast paths."""
        if not self._running:
            self.start()
        self._total_emitted += 1
        self._event_queue.put_nowait(event)

    async def _process_queue(self):
        """Worker loop reading events from queue and distributing to JSONL and subscribers."""
        while self._running or not self._event_queue.empty():
            try:
                # Wait for next event or timeout to check running flag
                try:
                    event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                event_json = event.model_dump_json()

                # 1. Write to JSONL
                if self._file_handle:
                    self._file_handle.write(event_json + "\n")
                    self._file_handle.flush()
                    self._total_written += 1

                # 2. Fan-out to all active WebSocket subscriber queues
                async with self._subscribers_lock:
                    stale_subscribers = []
                    for sub_q in self._subscribers:
                        try:
                            sub_q.put_nowait(event)
                        except asyncio.QueueFull:
                            # If a subscriber is lagging, drop or evict
                            pass
                        except Exception:
                            stale_subscribers.append(sub_q)
                    for stale in stale_subscribers:
                        self._subscribers.discard(stale)

                self._event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in telemetry bus worker: {e}", exc_info=True)

    async def register_subscriber(self, maxsize: int = 20000) -> asyncio.Queue[BaseEvent]:
        """Register a new subscriber queue (e.g. for a WebSocket connection)."""
        sub_queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=maxsize)
        async with self._subscribers_lock:
            self._subscribers.add(sub_queue)
        return sub_queue

    async def unregister_subscriber(self, sub_queue: asyncio.Queue[BaseEvent]):
        """Unregister a subscriber queue."""
        async with self._subscribers_lock:
            self._subscribers.discard(sub_queue)

    async def drain(self):
        """Wait until all queued events are fully processed and flushed."""
        if self._event_queue.qsize() > 0:
            await self._event_queue.join()
        if self._file_handle:
            self._file_handle.flush()

    async def close(self):
        """Stop worker and close open file handle."""
        await self.drain()
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        if self._file_handle:
            self._file_handle.flush()
            self._file_handle.close()
            self._file_handle = None

    @property
    def total_emitted(self) -> int:
        return self._total_emitted

    @property
    def total_written(self) -> int:
        return self._total_written


# Global default telemetry bus
GLOBAL_BUS = TelemetryBus()
