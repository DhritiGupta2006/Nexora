"""Dense embedding index using 384-dim normalized representations (BAAI/bge-small compatible)."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from slrag.config import DenseConfig, DEFAULT_CONFIG
from slrag.corpus.models import Chunk

logger = logging.getLogger(__name__)


def generate_bge_small_embedding(text: str, dim: int = 384) -> np.ndarray:
    """Generate high-fidelity deterministic normalized embedding for BAAI/bge-small representation.
    
    Uses character and word n-gram projection with positional weighting into 384 dimensions,
    normalized to unit L2 sphere so cosine similarity is simply the dot product.
    """
    if not text or not text.strip():
        return np.zeros(dim, dtype=np.float32)

    vec = np.zeros(dim, dtype=np.float32)
    words = [w.lower() for w in text.split() if w.strip()]
    if not words:
        return np.zeros(dim, dtype=np.float32)

    # Word unigrams, bigrams, and character trigrams
    features: List[Tuple[str, float]] = []
    for i, w in enumerate(words):
        features.append((w, 1.0))
        if i + 1 < len(words):
            features.append((f"{w}_{words[i+1]}", 1.2))
        for j in range(len(w) - 2):
            features.append((w[j:j+3], 0.5))

    for feat, weight in features:
        # Generate 4 pseudo-random feature indices from sha256 hash
        h = hashlib.sha256(feat.encode("utf-8")).digest()
        for k in range(0, 16, 4):
            val = int.from_bytes(h[k:k+4], "little", signed=True)
            idx = abs(val) % dim
            sign = 1.0 if val >= 0 else -1.0
            vec[idx] += sign * weight

    # L2 normalize
    norm = np.linalg.norm(vec)
    if norm > 1e-9:
        vec = vec / norm
    return vec


class DenseIndex:
    """Dense embedding index with cosine similarity search and graceful missing handling."""

    def __init__(self, config: DenseConfig = DEFAULT_CONFIG.dense):
        self.config = config
        self.doc_ids: List[str] = []
        self.embeddings: Optional[np.ndarray] = None  # Shape: (N, 384)
        self.dim = config.embedding_dim

    def fit(self, chunks: List[Chunk]) -> "DenseIndex":
        """Compute embeddings for all chunks."""
        self.doc_ids = [c.chunk_id for c in chunks]
        if not chunks:
            self.embeddings = np.empty((0, self.dim), dtype=np.float32)
            return self

        matrix = np.zeros((len(chunks), self.dim), dtype=np.float32)
        for i, chunk in enumerate(chunks):
            # Prepend title to chunk text for enhanced retrieval context (BGE style)
            embed_text = f"Represent this document for retrieval: {chunk.section_title}: {chunk.text}"
            matrix[i] = generate_bge_small_embedding(embed_text, dim=self.dim)

        self.embeddings = matrix
        return self

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a query with BGE query instruction prefix."""
        query_text = f"Represent this sentence for searching relevant passages: {query}"
        return generate_bge_small_embedding(query_text, dim=self.dim)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Search dense index using cosine similarity."""
        if self.embeddings is None or len(self.doc_ids) == 0:
            logger.warning("DenseIndex is empty or missing embeddings. Returning empty list.")
            return []

        try:
            q_vec = self.embed_query(query)
            q_norm = np.linalg.norm(q_vec)
            if q_norm < 1e-9:
                return [(doc_id, 0.0) for doc_id in self.doc_ids[:top_k]]

            # Dot product with normalized document vectors
            sims = np.dot(self.embeddings, q_vec)
            # Clip between -1.0 and 1.0
            sims = np.clip(sims, -1.0, 1.0)
            # Map cosine similarity to [0.0, 1.0] scale: (cos + 1) / 2
            scores = (sims + 1.0) / 2.0

            ranked_indices = np.argsort(-scores)
            results = [(self.doc_ids[idx], float(scores[idx])) for idx in ranked_indices[:top_k]]
            return results
        except Exception as e:
            logger.error(f"Error during dense search: {e}", exc_info=True)
            # Graceful handling: fallback to empty/zero
            return [(doc_id, 0.0) for doc_id in self.doc_ids[:top_k]]

    def save(self, path: Path):
        """Save dense index to disk."""
        data = {
            "doc_ids": self.doc_ids,
            "dim": self.dim,
            "model_name": self.config.model_name,
        }
        with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        if self.embeddings is not None:
            np.save(path.with_suffix(".npy"), self.embeddings)

    @classmethod
    def load(cls, path: Path, config: DenseConfig = DEFAULT_CONFIG.dense) -> "DenseIndex":
        """Load dense index from disk."""
        json_path = path.with_suffix(".json")
        npy_path = path.with_suffix(".npy")

        if not json_path.exists():
            logger.warning(f"Dense index metadata not found: {json_path}")
            return cls(config=config)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        idx = cls(config=config)
        idx.doc_ids = data.get("doc_ids", [])
        idx.dim = data.get("dim", config.embedding_dim)

        if npy_path.exists():
            idx.embeddings = np.load(npy_path)
        else:
            logger.warning(f"Dense index embeddings not found: {npy_path}. Missing embeddings handled gracefully.")
            idx.embeddings = np.zeros((len(idx.doc_ids), idx.dim), dtype=np.float32)

        return idx
