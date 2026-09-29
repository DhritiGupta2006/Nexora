"""Session registry with lazy initialization, per-session async locks, and idle cleanup."""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from slrag.config import SessionConfig, DEFAULT_CONFIG
from slrag.gateway.normalizer import EventNormalizer
from slrag.gateway.reorder_buffer import ReorderBuffer
from slrag.telemetry.metrics import MetricsCollector, GLOBAL_METRICS

logger = logging.getLogger(__name__)


class SessionContext:
    """Isolated state container for a single client interaction session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.lock = asyncio.Lock()  # Serializes mutations within this session
        self.normalizer = EventNormalizer()
        self.reorder_buffer = ReorderBuffer()
        self.turn_counter = 0
        self.created_at = time.time()
        self.last_activity = time.time()
        self.custom_state: Dict[str, any] = {}

    def touch(self):
        self.last_activity = time.time()

    def next_turn_id(self) -> str:
        self.turn_counter += 1
        return f"turn_{self.session_id}_{self.turn_counter:04d}"


class SessionRegistry:
    """Registry managing active session contexts, concurrency, and idle reclamation."""

    def __init__(
        self,
        config: SessionConfig = DEFAULT_CONFIG.session,
        metrics: Optional[MetricsCollector] = None,
    ):
        self.config = config
        self.metrics = metrics or GLOBAL_METRICS
        self._sessions: Dict[str, SessionContext] = {}
        self._registry_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def get_or_create(self, session_id: str) -> SessionContext:
        """Lazy creation of session context with thread-safe registry lock."""
        async with self._registry_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(session_id)
                self.metrics.set_active_sessions(len(self._sessions))
            ctx = self._sessions[session_id]
            ctx.touch()
            return ctx

    async def remove_session(self, session_id: str) -> bool:
        async with self._registry_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self.metrics.set_active_sessions(len(self._sessions))
                return True
            return False

    async def cleanup_idle_sessions(self) -> int:
        """Evict sessions that exceeded idle timeout."""
        now = time.time()
        timeout = self.config.idle_timeout_seconds
        evicted = 0

        async with self._registry_lock:
            to_remove = [
                sid for sid, ctx in self._sessions.items()
                if (now - ctx.last_activity) > timeout
            ]
            for sid in to_remove:
                del self._sessions[sid]
                evicted += 1
            if evicted > 0:
                self.metrics.set_active_sessions(len(self._sessions))
                logger.info(f"Cleaned up {evicted} idle sessions.")

        return evicted

    async def _cleanup_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self.cleanup_idle_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session cleanup loop: {e}", exc_info=True)

    @property
    def active_sessions_count(self) -> int:
        return len(self._sessions)


GLOBAL_SESSION_REGISTRY = SessionRegistry()
