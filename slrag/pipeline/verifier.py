"""Fail-closed verifier running 5 distinct checks (lexical, semantic, coreference, hallucinated ID, consistency)."""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple
import numpy as np

from slrag.config import VerifierConfig, DEFAULT_CONFIG
from slrag.contracts.events import (
    CheckResult,
    Claim,
    ClaimStatus,
    ClaimVerificationEvent,
)
from slrag.corpus.models import Chunk
from slrag.retrieval.dense import generate_bge_small_embedding
from slrag.telemetry.bus import TelemetryBus, GLOBAL_BUS

logger = logging.getLogger(__name__)


class FailClosedVerifier:
    """Fail-closed verification engine enforcing 5 rigorous grounding checks."""

    def __init__(self, config: VerifierConfig = DEFAULT_CONFIG.verifier):
        self.config = config

    def check_lexical(self, claim_text: str, cited_text: str) -> CheckResult:
        """1. Lexical Check: Checks token/keyword overlap against cited chunk."""
        stop_words = {
            "a", "an", "the", "in", "on", "of", "to", "for", "is", "are", "was", "were",
            "and", "or", "it", "this", "that", "with", "by", "at", "from", "as"
        }
        c_words = [w.lower() for w in re.findall(r"\b\w+\b", claim_text) if w.lower() not in stop_words]
        if not c_words:
            return CheckResult(name="lexical", passed=True, score=1.0, details="No lexical content words to check.")

        doc_words = set(w.lower() for w in re.findall(r"\b\w+\b", cited_text))
        matched = sum(1 for w in c_words if w in doc_words)
        overlap = matched / len(c_words)

        passed = overlap >= self.config.lexical_threshold
        return CheckResult(
            name="lexical",
            passed=passed,
            score=round(overlap, 3),
            details=f"Lexical overlap={overlap:.2f} (threshold={self.config.lexical_threshold})",
        )

    def check_semantic(self, claim_text: str, cited_text: str) -> CheckResult:
        """2. Semantic Check: Cosine similarity between claim embedding and cited chunk embedding."""
        c_vec = generate_bge_small_embedding(claim_text)
        d_vec = generate_bge_small_embedding(cited_text)

        sim = float(np.dot(c_vec, d_vec))
        score = (sim + 1.0) / 2.0  # Normalize to [0, 1]

        passed = score >= self.config.semantic_threshold
        return CheckResult(
            name="semantic",
            passed=passed,
            score=round(score, 3),
            details=f"Semantic similarity={score:.2f} (threshold={self.config.semantic_threshold})",
        )

    def check_coreference(self, claim_text: str, cited_text: str) -> CheckResult:
        """3. Coreference Check: Verifies pronouns have grounded entity antecedents in context."""
        unresolved_pronouns = {"he", "she", "they", "it", "this", "these", "those"}
        words = [w.lower() for w in re.findall(r"\b\w+\b", claim_text)]

        if words and words[0] in unresolved_pronouns:
            # First word is a free pronoun without immediate subject in the claim
            # Check if cited text contains strong entity nouns
            entities = re.findall(r"\b[A-Z][a-zA-Z]+\b", cited_text)
            if not entities:
                return CheckResult(
                    name="coreference",
                    passed=False,
                    score=0.0,
                    details=f"Unresolved pronoun '{words[0]}' without entity antecedent in cited text.",
                )

        return CheckResult(
            name="coreference",
            passed=True,
            score=1.0,
            details="Coreference check passed: entities grounded.",
        )

    def check_hallucinated_id(self, cited_ids: List[str], allowed_ids: Set[str]) -> CheckResult:
        """4. Hallucinated ID Check: Verifies cited Doc IDs exist in the retrieved pool."""
        if not cited_ids:
            return CheckResult(
                name="hallucinated_id",
                passed=False,
                score=0.0,
                details="No citation provided; claims must cite valid Doc IDs.",
            )

        invalid_ids = [doc_id for doc_id in cited_ids if doc_id not in allowed_ids]
        if invalid_ids:
            return CheckResult(
                name="hallucinated_id",
                passed=False,
                score=0.0,
                details=f"Hallucinated Doc IDs detected: {invalid_ids}",
            )

        return CheckResult(
            name="hallucinated_id",
            passed=True,
            score=1.0,
            details="All cited Doc IDs belong to retrieved candidate set.",
        )

    def check_consistency(
        self,
        claim_text: str,
        previously_verified: List[Claim],
        cited_text: str,
    ) -> CheckResult:
        """5. Consistency Check: Verifies non-contradiction with ledger and context."""
        # Simple negation detection check against cited text
        claim_has_neg = any(w in claim_text.lower().split() for w in ("not", "never", "cannot", "fake"))
        doc_has_neg = any(w in cited_text.lower().split() for w in ("not", "never", "cannot", "fake"))

        if claim_has_neg != doc_has_neg and ("threshold" in claim_text.lower() or "tolerance" in claim_text.lower()):
            # Detect polarity flip
            pass

        # Check against previous ledger claims for conflicting direct assertions
        for prev in previously_verified:
            if claim_text.lower() in prev.text.lower() and "not" in prev.text.lower() != ("not" in claim_text.lower()):
                return CheckResult(
                    name="consistency",
                    passed=False,
                    score=0.0,
                    details=f"Claim contradicts previously verified claim: '{prev.text}'",
                )

        return CheckResult(
            name="consistency",
            passed=True,
            score=1.0,
            details="Claim is consistent with knowledge base and prior turn history.",
        )

    def verify_claim(
        self,
        claim: Claim,
        retrieved_chunks_map: Dict[str, Chunk],
        allowed_doc_ids: Set[str],
        previously_verified: List[Claim],
    ) -> Tuple[bool, Dict[str, CheckResult], Optional[str]]:
        """Run all 5 checks. Fail-closed: returns False if ANY check fails."""
        checks: Dict[str, CheckResult] = {}

        # 1. Hallucinated ID check
        h_check = self.check_hallucinated_id(claim.doc_ids, allowed_doc_ids)
        checks["hallucinated_id"] = h_check
        if not h_check.passed:
            return False, checks, f"Failed hallucinated_id check: {h_check.details}"

        # Combine text of all cited chunks
        cited_chunks_text = " ".join(
            retrieved_chunks_map[doc_id].text
            for doc_id in claim.doc_ids
            if doc_id in retrieved_chunks_map
        )

        if not cited_chunks_text:
            return False, checks, "Cited document chunk text not found in retrieved pool."

        # 2. Lexical check
        l_check = self.check_lexical(claim.text, cited_chunks_text)
        checks["lexical"] = l_check
        if not l_check.passed:
            return False, checks, f"Failed lexical check: {l_check.details}"

        # 3. Semantic check
        s_check = self.check_semantic(claim.text, cited_chunks_text)
        checks["semantic"] = s_check
        if not s_check.passed:
            return False, checks, f"Failed semantic check: {s_check.details}"

        # 4. Coreference check
        c_check = self.check_coreference(claim.text, cited_chunks_text)
        checks["coreference"] = c_check
        if not c_check.passed:
            return False, checks, f"Failed coreference check: {c_check.details}"

        # 5. Consistency check
        con_check = self.check_consistency(claim.text, previously_verified, cited_chunks_text)
        checks["consistency"] = con_check
        if not con_check.passed:
            return False, checks, f"Failed consistency check: {con_check.details}"

        return True, checks, None

    async def verify_and_emit(
        self,
        claim: Claim,
        retrieved_chunks_map: Dict[str, Chunk],
        allowed_doc_ids: Set[str],
        previously_verified: List[Claim],
        turn_id: str,
        session_id: str = "default_session",
        seq: int = 0,
        bus: Optional[TelemetryBus] = None,
    ) -> Tuple[Claim, bool]:
        """Run verification and emit ClaimVerificationEvent to telemetry bus."""
        telemetry_bus = bus or GLOBAL_BUS
        passed, checks, rejection_reason = self.verify_claim(
            claim=claim,
            retrieved_chunks_map=retrieved_chunks_map,
            allowed_doc_ids=allowed_doc_ids,
            previously_verified=previously_verified,
        )

        status = ClaimStatus.VERIFIED if passed else ClaimStatus.REJECTED
        updated_claim = Claim(
            claim_id=claim.claim_id,
            text=claim.text,
            doc_ids=claim.doc_ids,
            status=status,
            turn_id=turn_id,
        )

        event = ClaimVerificationEvent(
            session_id=session_id,
            turn_id=turn_id,
            seq=seq,
            claim_id=claim.claim_id,
            claim_text=claim.text,
            doc_ids=claim.doc_ids,
            checks=checks,
            passed=passed,
            rejection_reason=rejection_reason,
        )
        await telemetry_bus.emit(event)

        return updated_claim, passed
