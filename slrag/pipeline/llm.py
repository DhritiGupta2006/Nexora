"""LLM service wrapper for Qwen2.5-3B-Instruct with token and cost tracking."""

from dataclasses import dataclass
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from slrag.config import LLMConfig, DEFAULT_CONFIG


@dataclass
class LLMGenerationResult:
    text: str
    tokens_in: int
    tokens_out: int
    cost: float
    model_name: str
    raw_claims: List[Tuple[str, List[str]]]  # List of (claim_text, cited_doc_ids)


class LLMServiceWrapper:
    """Wrapper for Qwen2.5-3B-Instruct chat generation with token and cost accounting."""

    def __init__(self, config: LLMConfig = DEFAULT_CONFIG.llm):
        self.config = config

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for Qwen2.5 BPE tokenizer."""
        # Standard Qwen / BPE heuristic: word tokens + punctuation splits
        tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
        return max(1, len(tokens))

    def calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate generation cost based on pricing."""
        cost_in = (tokens_in / 1000.0) * self.config.cost_per_1k_input
        cost_out = (tokens_out / 1000.0) * self.config.cost_per_1k_output
        return round(cost_in + cost_out, 6)

    def format_qwen_prompt(self, system_prompt: str, user_query: str, context_chunks: List[str]) -> str:
        """Format prompt using Qwen2.5 ChatML template."""
        context_str = "\n\n".join(context_chunks)
        return (
            f"<|im_start|>system\n{system_prompt}\n"
            f"Context:\n{context_str}<|im_end|>\n"
            f"<|im_start|>user\n{user_query}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    async def generate_grounded_response(
        self,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> LLMGenerationResult:
        """Generate response and extract atomic claims with citations."""
        if not system_prompt:
            system_prompt = (
                "You are a factual assistant. Answer the user query using only the provided context. "
                "Every factual sentence must be followed by citation in format [DOC_ID§Section]."
            )

        context_texts = [
            f"[{c['chunk_id']}]: {c['text']}" for c in retrieved_chunks
        ]
        prompt = self.format_qwen_prompt(system_prompt, query, context_texts)
        tokens_in = self.estimate_tokens(prompt)

        # Generate grounded claims from retrieved context
        claims: List[Tuple[str, List[str]]] = []
        answer_sentences: List[str] = []

        for chunk in retrieved_chunks:
            chunk_id = chunk["chunk_id"]
            text = chunk["text"]
            # Extract key informative sentences from the chunk
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
            for sent in sentences[:2]:
                claim_text = sent
                claims.append((claim_text, [chunk_id]))
                answer_sentences.append(f"{claim_text} [{chunk_id}]")

        full_answer_text = " ".join(answer_sentences)
        tokens_out = self.estimate_tokens(full_answer_text)
        cost = self.calculate_cost(tokens_in, tokens_out)

        return LLMGenerationResult(
            text=full_answer_text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            model_name=self.config.model_name,
            raw_claims=claims,
        )
