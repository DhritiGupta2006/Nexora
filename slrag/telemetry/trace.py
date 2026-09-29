"""Trace coverage checker validating lifecycle event sequences per turn type."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from slrag.contracts.events import BaseEvent


@dataclass
class TraceValidationResult:
    turn_id: str
    turn_type: str  # "sufficient" | "insufficient" | "unknown"
    is_valid: bool
    observed_events: List[str]
    missing_events: List[str]
    errors: List[str]


class TraceCoverageChecker:
    """Validates that turns produce complete, well-formed telemetry trace event sequences."""

    REQUIRED_SUFFICIENT_EVENTS = [
        "transcript_chunk",
        "utterance_end",
        "retrieval",
        "sufficiency_check",
        "claim_verification",
        "answer_delta",
        "ledger_update",
        "turn_summary",
    ]

    REQUIRED_INSUFFICIENT_EVENTS = [
        "transcript_chunk",
        "utterance_end",
        "retrieval",
        "sufficiency_check",
        "answer_delta",
        "turn_summary",
    ]

    @classmethod
    def validate_turn_trace(cls, events: List[BaseEvent], turn_id: Optional[str] = None) -> TraceValidationResult:
        """Validate an event trace sequence for a given turn."""
        if not events:
            return TraceValidationResult(
                turn_id=turn_id or "unknown",
                turn_type="unknown",
                is_valid=False,
                observed_events=[],
                missing_events=["empty_trace"],
                errors=["No events observed in turn trace."],
            )

        observed_types = [e.event_type for e in events]
        observed_set = set(observed_types)

        # Detect turn type based on sufficiency check event
        turn_type = "sufficient"
        for e in events:
            if e.event_type == "sufficiency_check" and hasattr(e, "passed") and not getattr(e, "passed"):
                turn_type = "insufficient"
                break

        required = (
            cls.REQUIRED_INSUFFICIENT_EVENTS
            if turn_type == "insufficient"
            else cls.REQUIRED_SUFFICIENT_EVENTS
        )

        missing = [req for req in required if req not in observed_set]
        errors = []

        if missing:
            errors.append(f"Missing required lifecycle events: {missing}")

        # Check turn_id consistency if provided
        if turn_id:
            for e in events:
                e_turn = getattr(e, "turn_id", None)
                if e_turn and e_turn != turn_id:
                    errors.append(f"Event {e.event_id} has turn_id '{e_turn}', expected '{turn_id}'")

        is_valid = len(missing) == 0 and len(errors) == 0

        return TraceValidationResult(
            turn_id=turn_id or getattr(events[-1], "turn_id", "unknown"),
            turn_type=turn_type,
            is_valid=is_valid,
            observed_events=observed_types,
            missing_events=missing,
            errors=errors,
        )
