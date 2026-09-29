"""Unified Hybrid Retrieval Engine combining BM25, Dense embeddings, and RRF."""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from slrag.config import AppConfig, DEFAULT_CONFIG
from slrag.corpus.models import Chunk, Document
from slrag.corpus.chunker import SectionAwareChunker
from slrag.retrieval.bm25 import BM25Index
from slrag.retrieval.dense import DenseIndex
from slrag.retrieval.fusion import FusedResult, reciprocal_rank_fusion

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    rank: int
    text: str
    section_title: str
    doc_id: str
    metadata: Dict[str, Any]
    source_scores: Dict[str, Any]


class HybridRetrievalEngine:
    """Production hybrid retrieval engine with BM25, Dense embeddings, and RRF."""

    def __init__(self, config: AppConfig = DEFAULT_CONFIG):
        self.config = config
        self.chunks_map: Dict[str, Chunk] = {}
        self.bm25_index = BM25Index(config.bm25)
        self.dense_index = DenseIndex(config.dense)

    def index_documents(self, docs: List[Document]) -> int:
        """Chunk and index documents."""
        chunker = SectionAwareChunker(self.config.chunker)
        chunks = chunker.chunk_documents(docs)
        return self.index_chunks(chunks)

    def index_chunks(self, chunks: List[Chunk]) -> int:
        """Build BM25 and Dense index from chunks."""
        self.chunks_map = {c.chunk_id: c for c in chunks}
        self.bm25_index.fit(chunks)
        self.dense_index.fit(chunks)
        logger.info(f"Indexed {len(chunks)} chunks successfully.")
        return len(chunks)

    def search(
        self,
        query: str,
        mode: Literal["bm25", "dense", "hybrid"] = "hybrid",
        top_k: int = 10,
    ) -> List[SearchResult]:
        """Query retrieval engine using specified mode."""
        if not self.chunks_map:
            return []

        mode = mode.lower()  # type: ignore

        if mode == "bm25":
            raw_results = self.bm25_index.search(query, top_k=top_k)
            results = []
            for rank_0, (chunk_id, score) in enumerate(raw_results):
                chunk = self.chunks_map.get(chunk_id)
                if not chunk:
                    continue
                results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        score=score,
                        rank=rank_0 + 1,
                        text=chunk.text,
                        section_title=chunk.section_title,
                        doc_id=chunk.doc_id,
                        metadata=chunk.metadata,
                        source_scores={"bm25_score": score},
                    )
                )
            return results

        elif mode == "dense":
            raw_results = self.dense_index.search(query, top_k=top_k)
            results = []
            for rank_0, (chunk_id, score) in enumerate(raw_results):
                chunk = self.chunks_map.get(chunk_id)
                if not chunk:
                    continue
                results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        score=score,
                        rank=rank_0 + 1,
                        text=chunk.text,
                        section_title=chunk.section_title,
                        doc_id=chunk.doc_id,
                        metadata=chunk.metadata,
                        source_scores={"dense_score": score},
                    )
                )
            return results

        elif mode == "hybrid":
            # Retrieve candidate pools from both
            pool_size = max(top_k * 3, 50)
            bm25_ranked = self.bm25_index.score_query(query)[:pool_size]
            dense_ranked = self.dense_index.search(query, top_k=pool_size)

            fused: List[FusedResult] = reciprocal_rank_fusion(
                bm25_results=bm25_ranked,
                dense_results=dense_ranked,
                config=self.config.rrf,
                top_k=top_k,
            )

            results = []
            for rank_0, item in enumerate(fused):
                chunk = self.chunks_map.get(item.chunk_id)
                if not chunk:
                    continue
                results.append(
                    SearchResult(
                        chunk_id=item.chunk_id,
                        score=item.rrf_score,
                        rank=rank_0 + 1,
                        text=chunk.text,
                        section_title=chunk.section_title,
                        doc_id=chunk.doc_id,
                        metadata=chunk.metadata,
                        source_scores={
                            "rrf_score": item.rrf_score,
                            "bm25_rank": item.bm25_rank,
                            "bm25_score": item.bm25_score,
                            "dense_rank": item.dense_rank,
                            "dense_score": item.dense_score,
                        },
                    )
                )
            return results

        else:
            raise ValueError(f"Unknown retrieval mode: {mode}. Must be 'bm25', 'dense', or 'hybrid'.")

    def save(self, dir_path: Path):
        """Persist engine state and indices to disk."""
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        # Save chunks
        chunks_data = [c.to_dict() for c in self.chunks_map.values()]
        with open(dir_path / "chunks.json", "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, indent=2)

        # Save BM25
        self.bm25_index.save(dir_path / "bm25_index.json")

        # Save Dense
        self.dense_index.save(dir_path / "dense_index")

        # Save metadata
        meta = {
            "total_chunks": len(self.chunks_map),
            "cfg_hash": self.config.cfg_hash,
            "saved_at": time.time(),
        }
        with open(dir_path / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, dir_path: Path, config: AppConfig = DEFAULT_CONFIG) -> "HybridRetrievalEngine":
        """Load engine and indices from disk."""
        dir_path = Path(dir_path)
        engine = cls(config=config)

        chunks_file = dir_path / "chunks.json"
        if chunks_file.exists():
            with open(chunks_file, "r", encoding="utf-8") as f:
                raw_chunks = json.load(f)
                chunks = [Chunk.from_dict(d) for d in raw_chunks]
                engine.chunks_map = {c.chunk_id: c for c in chunks}

        bm25_file = dir_path / "bm25_index.json"
        if bm25_file.exists():
            engine.bm25_index = BM25Index.load(bm25_file, config=config.bm25)

        dense_prefix = dir_path / "dense_index"
        if (dir_path / "dense_index.json").exists():
            engine.dense_index = DenseIndex.load(dense_prefix, config=config.dense)

        return engine

    def get_stats(self) -> Dict[str, Any]:
        """Return engine corpus and index statistics."""
        return {
            "total_chunks": len(self.chunks_map),
            "vocab_size": len(self.bm25_index.vocab),
            "avg_doc_length": round(self.bm25_index.avg_doc_length, 2),
            "dense_embeddings_shape": list(self.dense_index.embeddings.shape) if self.dense_index.embeddings is not None else [0, 0],
            "cfg_hash": self.config.cfg_hash,
        }
