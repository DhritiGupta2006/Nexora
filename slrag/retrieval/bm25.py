"""BM25 Okapi indexing and retrieval engine with stored postings and IDF table."""

from collections import Counter
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple
from slrag.config import BM25Config, DEFAULT_CONFIG
from slrag.corpus.models import Chunk


def tokenize(text: str) -> List[str]:
    """Normalize and tokenize text into lowercase word tokens."""
    return re.findall(r"\b\w+\b", text.lower(), re.UNICODE)


class BM25Index:
    """Okapi BM25 Index with inverted postings, vocabulary, and IDF table."""

    def __init__(self, config: BM25Config = DEFAULT_CONFIG.bm25):
        self.config = config
        self.vocab: Dict[str, int] = {}  # token -> term_id
        self.inv_vocab: List[str] = []   # term_id -> token
        self.idf_table: Dict[str, float] = {}  # token -> IDF score
        self.postings: Dict[str, List[Tuple[int, int]]] = {}  # token -> [(doc_idx, tf), ...]
        self.doc_lengths: List[int] = []  # doc_idx -> doc token length
        self.doc_ids: List[str] = []      # doc_idx -> chunk_id
        self.avg_doc_length: float = 0.0
        self.num_docs: int = 0

    def fit(self, chunks: List[Chunk]) -> "BM25Index":
        """Build BM25 index from a list of chunks."""
        self.num_docs = len(chunks)
        self.doc_ids = [c.chunk_id for c in chunks]
        self.doc_lengths = []
        self.postings = {}
        self.vocab = {}
        self.inv_vocab = []

        total_length = 0
        doc_freqs: Dict[str, int] = Counter()

        for doc_idx, chunk in enumerate(chunks):
            tokens = tokenize(chunk.text)
            doc_len = len(tokens)
            self.doc_lengths.append(doc_len)
            total_length += doc_len

            term_counts = Counter(tokens)
            for token, tf in term_counts.items():
                if token not in self.vocab:
                    term_id = len(self.inv_vocab)
                    self.vocab[token] = term_id
                    self.inv_vocab.append(token)
                    self.postings[token] = []
                self.postings[token].append((doc_idx, tf))
                doc_freqs[token] += 1

        self.avg_doc_length = total_length / self.num_docs if self.num_docs > 0 else 0.0

        # Calculate IDF for every token in vocab
        # Standard Lucene/BM25 Okapi IDF formula: ln(1 + (N - df + 0.5) / (df + 0.5))
        self.idf_table = {}
        for token, df in doc_freqs.items():
            idf = math.log(1.0 + (self.num_docs - df + 0.5) / (df + 0.5))
            self.idf_table[token] = max(self.config.epsilon, idf)

        return self

    def score_query(self, query: str) -> List[Tuple[str, float]]:
        """Score all documents against a query string using Okapi BM25."""
        if self.num_docs == 0:
            return []

        q_tokens = tokenize(query)
        if not q_tokens:
            return [(doc_id, 0.0) for doc_id in self.doc_ids]

        scores = [0.0] * self.num_docs
        k1 = self.config.k1
        b = self.config.b
        avgdl = self.avg_doc_length if self.avg_doc_length > 0 else 1.0

        for token in q_tokens:
            if token not in self.postings:
                continue
            idf = self.idf_table.get(token, 0.0)
            for doc_idx, tf in self.postings[token]:
                doc_len = self.doc_lengths[doc_idx]
                numerator = tf * (k1 + 1.0)
                denominator = tf + k1 * (1.0 - b + b * (doc_len / avgdl))
                scores[doc_idx] += idf * (numerator / denominator)

        ranked = [(self.doc_ids[i], scores[i]) for i in range(self.num_docs)]
        ranked.sort(key=lambda x: (-x[1], x[0]))
        return ranked

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Return top_k ranked (chunk_id, bm25_score)."""
        ranked = self.score_query(query)
        return ranked[:top_k]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vocab": self.vocab,
            "inv_vocab": self.inv_vocab,
            "idf_table": self.idf_table,
            "postings": {k: [list(item) for item in v] for k, v in self.postings.items()},
            "doc_lengths": self.doc_lengths,
            "doc_ids": self.doc_ids,
            "avg_doc_length": self.avg_doc_length,
            "num_docs": self.num_docs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], config: BM25Config = DEFAULT_CONFIG.bm25) -> "BM25Index":
        idx = cls(config=config)
        idx.vocab = data["vocab"]
        idx.inv_vocab = data["inv_vocab"]
        idx.idf_table = data["idf_table"]
        idx.postings = {k: [(item[0], item[1]) for item in v] for k, v in data["postings"].items()}
        idx.doc_lengths = data["doc_lengths"]
        idx.doc_ids = data["doc_ids"]
        idx.avg_doc_length = data["avg_doc_length"]
        idx.num_docs = data["num_docs"]
        return idx

    def save(self, path: Path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: Path, config: BM25Config = DEFAULT_CONFIG.bm25) -> "BM25Index":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, config)
