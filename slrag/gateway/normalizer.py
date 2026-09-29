"""Gateway normalizer for event key variations and cumulative vs delta text merging."""

from typing import Any, Dict, Optional, Tuple
from slrag.contracts.events import BaseEvent, TranscriptChunk, UtteranceEnd


class EventNormalizer:
    """Normalizes raw input dictionaries and handles cumulative/delta speech text streams."""

    def __init__(self):
        self._cumulative_text: str = ""

    def normalize_dict_keys(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common key synonyms across different streaming clients."""
        normalized = dict(raw_data)

        # Map text synonyms
        if "text" not in normalized:
            for alias in ("transcript", "content", "message", "utterance"):
                if alias in normalized:
                    normalized["text"] = str(normalized[alias])
                    break

        # Map seq synonyms
        if "seq" not in normalized:
            for alias in ("seq_no", "sequence", "seq_num", "index"):
                if alias in normalized:
                    try:
                        normalized["seq"] = int(normalized[alias])
                    except (ValueError, TypeError):
                        pass
                    break

        # Map utterance_id / turn_id synonyms
        if "turn_id" not in normalized:
            for alias in ("turnId", "turn", "session_turn"):
                if alias in normalized:
                    normalized["turn_id"] = str(normalized[alias])
                    break

        if "utterance_id" not in normalized:
            for alias in ("utteranceId", "utterance_no", "utt_id"):
                if alias in normalized:
                    normalized["utterance_id"] = str(normalized[alias])
                    break

        # Map is_final synonyms
        if "is_final" not in normalized:
            for alias in ("isFinal", "final", "complete"):
                if alias in normalized:
                    normalized["is_final"] = bool(normalized[alias])
                    break

        return normalized

    def process_transcript_text(self, new_text: str, is_cumulative: Optional[bool] = None) -> Tuple[str, str]:
        """Process incoming speech text.
        
        Returns:
            (delta_text, current_full_text)
        """
        new_text = new_text.strip()
        
        # Auto-detect cumulative if not specified
        if is_cumulative is None:
            # If new_text starts with the existing cumulative text, it's cumulative
            is_cumulative = bool(self._cumulative_text and new_text.startswith(self._cumulative_text))

        if is_cumulative:
            if new_text.startswith(self._cumulative_text):
                delta = new_text[len(self._cumulative_text):].strip()
            else:
                delta = new_text
            self._cumulative_text = new_text
        else:
            delta = new_text
            if self._cumulative_text:
                self._cumulative_text = f"{self._cumulative_text} {delta}".strip()
            else:
                self._cumulative_text = delta

        return delta, self._cumulative_text

    def reset_utterance(self) -> str:
        """Reset accumulated text state at utterance boundary and return full utterance."""
        full = self._cumulative_text
        self._cumulative_text = ""
        return full
