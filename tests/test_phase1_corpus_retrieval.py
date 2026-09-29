"""Unit tests for Phase 1: Corpus Ingestion, Chunker, BM25, Dense, RRF Fusion, and CLI."""

import json
from pathlib import Path
import pytest

from slrag.config import DEFAULT_CONFIG
from slrag.corpus.chunker import SectionAwareChunker
from slrag.corpus.loader import CorpusLoader
from slrag.corpus.models import Document, Section
from slrag.retrieval.bm25 import BM25Index
from slrag.retrieval.dense import DenseIndex
from slrag.retrieval.engine import HybridRetrievalEngine
from slrag.retrieval.fusion import reciprocal_rank_fusion


CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_corpus.json"


def test_stable_chunk_ids():
    """Verify that chunk IDs are 100% deterministic and reproducible across multiple runs."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    chunker = SectionAwareChunker(DEFAULT_CONFIG.chunker)

    run1_chunks = chunker.chunk_documents(docs)
    run2_chunks = chunker.chunk_documents(docs)

    assert len(run1_chunks) == len(run2_chunks)
    for c1, c2 in zip(run1_chunks, run2_chunks):
        assert c1.chunk_id == c2.chunk_id
        assert c1.chunk_hash == c2.chunk_hash
        assert "§" in c1.chunk_id
        assert c1.doc_id in c1.chunk_id


def test_bm25_indexing_and_ranking():
    """Verify BM25 index scoring and keyword precision."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    chunker = SectionAwareChunker(DEFAULT_CONFIG.chunker)
    chunks = chunker.chunk_documents(docs)

    bm25 = BM25Index(DEFAULT_CONFIG.bm25).fit(chunks)
    assert bm25.num_docs == len(chunks)
    assert len(bm25.vocab) > 0

    # Query with specific keywords
    results = bm25.search("SSTable MemTable write ahead log RocksDB", top_k=3)
    assert len(results) > 0
    top_chunk_id, top_score = results[0]
    assert top_chunk_id == "DOC003§lsm_trees"
    assert top_score > 0.0


def test_dense_retrieval_ranking():
    """Verify Dense embedding similarity retrieval."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    chunker = SectionAwareChunker(DEFAULT_CONFIG.chunker)
    chunks = chunker.chunk_documents(docs)

    dense = DenseIndex(DEFAULT_CONFIG.dense).fit(chunks)
    assert dense.embeddings is not None
    assert dense.embeddings.shape == (len(chunks), 384)

    results = dense.search("approximate nearest neighbor graph vector search", top_k=3)
    assert len(results) > 0
    top_chunk_id, top_score = results[0]
    assert top_chunk_id == "DOC004§hnsw_indexing"
    assert 0.0 <= top_score <= 1.0


def test_missing_embeddings_graceful_handling():
    """Verify system handles missing or empty embeddings without raising unhandled exceptions."""
    dense = DenseIndex(DEFAULT_CONFIG.dense)
    # Empty search
    res = dense.search("some test query", top_k=5)
    assert res == []

    # Corrupted / zero embedding matrix
    dense.doc_ids = ["DOC1§sec1", "DOC2§sec2"]
    dense.embeddings = None
    res2 = dense.search("some test query", top_k=5)
    assert res2 == []


def test_rrf_fusion_merging():
    """Verify RRF merges lexical and dense lists deterministically with correct rank scores."""
    bm25_res = [("CHUNK_A", 12.5), ("CHUNK_B", 8.2), ("CHUNK_C", 3.1)]
    dense_res = [("CHUNK_B", 0.95), ("CHUNK_A", 0.88), ("CHUNK_D", 0.70)]

    fused = reciprocal_rank_fusion(bm25_res, dense_res, config=DEFAULT_CONFIG.rrf, top_k=4)
    assert len(fused) == 4

    # Both CHUNK_A and CHUNK_B appear at top ranks in both lists, so they should lead
    top_ids = [f.chunk_id for f in fused]
    assert "CHUNK_A" in top_ids[:2]
    assert "CHUNK_B" in top_ids[:2]
    assert all(f.rrf_score > 0.0 for f in fused)


def test_hybrid_recall_exceeds_or_equals_dense():
    """Verify that hybrid retrieval recall@10 >= dense-only recall@10 across a test suite."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    engine.index_documents(docs)

    test_queries = [
        # Query, Expected ground truth chunk ID
        ("qubit superposition entanglement Shor algorithm", "DOC001§intro"),
        ("surface code physical qubits square lattice error threshold", "DOC001§error_correction"),
        ("Raft leader election candidate follower quorum state machine", "DOC002§raft_consensus"),
        ("vector clock causality Lamport happens before relation", "DOC002§vector_clocks"),
        ("LSM Tree MemTable SSTable tiered leveled compaction", "DOC003§lsm_trees"),
        ("B+Tree doubly linked leaf nodes disk pages range scans", "DOC003§b_trees"),
        ("HNSW approximate nearest neighbor skip links dense vector", "DOC004§hnsw_indexing"),
        ("Okapi BM25 inverse document frequency k1 b parameter", "DOC004§bm25_lexical"),
    ]

    dense_hits = 0
    hybrid_hits = 0

    for query, expected_chunk in test_queries:
        dense_res = [r.chunk_id for r in engine.search(query, mode="dense", top_k=1)]
        hybrid_res = [r.chunk_id for r in engine.search(query, mode="hybrid", top_k=1)]

        if expected_chunk in dense_res:
            dense_hits += 1
        if expected_chunk in hybrid_res:
            hybrid_hits += 1

    dense_recall = dense_hits / len(test_queries)
    hybrid_recall = hybrid_hits / len(test_queries)

    assert hybrid_recall >= dense_recall
    assert hybrid_recall == 1.0  # Hybrid achieves 100% top-1 recall on benchmark suite


def test_hybrid_engine_save_load(tmp_path):
    """Verify engine serialization and index loading from disk."""
    docs = CorpusLoader.load_file(CORPUS_PATH)
    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    engine.index_documents(docs)

    index_dir = tmp_path / "test_index"
    engine.save(index_dir)

    loaded_engine = HybridRetrievalEngine.load(index_dir, config=DEFAULT_CONFIG)
    assert len(loaded_engine.chunks_map) == len(engine.chunks_map)

    res = loaded_engine.search("LSM tree SSTable compaction", mode="hybrid", top_k=2)
    assert len(res) > 0
    assert res[0].chunk_id == "DOC003§lsm_trees"
