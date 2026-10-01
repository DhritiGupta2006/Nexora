"""Generic prompts for the Phase 7 delta planner and rewriter (domain-agnostic)."""
from __future__ import annotations

import json
from typing import Any, Dict, List

DELTA_PLANNER_PROMPT = """You maintain a grounded answer made of claims, grouped by sub-question.
The user just said something new. Decide how it relates to the existing answer:
- "modifies": it changes the conditions of an existing sub-question (dates, exceptions, scope, quantities);
- "adds": it asks a new question in the same conversation;
- "unrelated": it starts a new topic.
Name the ids of the sub-questions it affects (only for "modifies"), and propose at most 2 short
retrieval queries that capture only what is new. Reply with JSON matching the schema.

New statement: {utterance}
Sub-questions: {sub_intents}
Claims (first 20 words): {claims}
Schema: {schema}"""

REWRITER_PROMPT = """You revise a grounded answer after the user added a constraint.
For every claim below choose "keep" (still correct under the constraint), "revise" (give the
corrected text and cites) or "retract" (no longer true). You may add up to 3 new claims for the
listed sub-questions. Use only the evidence below and cite only the allowed chunk ids.
Reply with JSON matching the schema.

Constraint: {constraint}
Claims: {claims}
New evidence: {evidence}
Schema: {schema}"""


def first_words(text: str, n: int = 20) -> str:
    return " ".join(text.split()[:n])


def delta_planner_prompt(utterance: str, sub_intents: List[Dict[str, Any]], claims: List[Dict[str, Any]], schema: Dict[str, Any]) -> str:
    return DELTA_PLANNER_PROMPT.format(
        utterance=utterance, sub_intents=json.dumps(sub_intents, ensure_ascii=False),
        claims=json.dumps(claims, ensure_ascii=False), schema=json.dumps(schema),
    )


def rewriter_prompt(constraint: str, claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]], schema: Dict[str, Any]) -> str:
    return REWRITER_PROMPT.format(
        constraint=constraint, claims=json.dumps(claims, ensure_ascii=False),
        evidence=json.dumps(evidence, ensure_ascii=False), schema=json.dumps(schema),
    )
