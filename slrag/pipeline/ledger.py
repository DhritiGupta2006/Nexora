"""Claim ledger v1 with versioning, history tracking, and session persistence."""

import logging
from typing import Dict, List, Optional
from slrag.contracts.events import Claim, ClaimStatus, Ledger
from slrag.telemetry.bus import TelemetryBus, GLOBAL_BUS

logger = logging.getLogger(__name__)


class ClaimLedger:
    """Session-scoped versioned ledger recording all verified claims across turns."""

    def __init__(self, session_id: str = "default_session"):
        self.session_id = session_id
        self.version = 1
        self._verified_claims: List[Claim] = []
        self._claims_by_turn: Dict[str, List[Claim]] = {}

    def get_verified_claims(self) -> List[Claim]:
        """Return all active verified claims."""
        return list(self._verified_claims)

    def add_verified_claims(self, claims: List[Claim], turn_id: str) -> int:
        """Append new verified claims, increment ledger version, and record turn history."""
        added = 0
        for c in claims:
            if c.status == ClaimStatus.VERIFIED:
                self._verified_claims.append(c)
                if turn_id not in self._claims_by_turn:
                    self._claims_by_turn[turn_id] = []
                self._claims_by_turn[turn_id].append(c)
                added += 1

        if added > 0:
            self.version += 1
            logger.debug(f"Ledger version bumped to {self.version} for session {self.session_id} (+{added} claims)")

        return self.version

    def create_snapshot_event(self, turn_id: str, seq: int = 0) -> Ledger:
        """Generate frozen Ledger event snapshot."""
        return Ledger(
            session_id=self.session_id,
            active_turn_id=turn_id,
            seq=seq,
            ledger_version=self.version,
            verified_claims=list(self._verified_claims),
        )

    async def emit_snapshot(
        self,
        turn_id: str,
        seq: int = 0,
        bus: Optional[TelemetryBus] = None,
    ) -> Ledger:
        """Emit current ledger snapshot event to the telemetry bus."""
        telemetry_bus = bus or GLOBAL_BUS
        snapshot = self.create_snapshot_event(turn_id, seq)
        await telemetry_bus.emit(snapshot)
        return snapshot
