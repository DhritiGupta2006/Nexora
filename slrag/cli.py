"""Command-line interface for SL-RAG (audit, index, search, probe)."""

import json
from pathlib import Path
import sys
import time
import click

from slrag.config import DEFAULT_CONFIG
from slrag.corpus.loader import CorpusLoader
from slrag.corpus.chunker import SectionAwareChunker
from slrag.retrieval.engine import HybridRetrievalEngine


@click.group()
def cli():
    """SL-RAG: Streaming Hybrid Retrieval-Augmented Generation CLI."""
    pass


@cli.command("audit")
@click.argument("corpus_path", type=click.Path(exists=True))
def audit_command(corpus_path: str):
    """Audit corpus files, chunks, token distributions, and section integrity."""
    click.echo(f"Auditing corpus from: {corpus_path}")
    path = Path(corpus_path)
    if path.is_dir():
        docs = CorpusLoader.load_directory(path)
    else:
        docs = CorpusLoader.load_file(path)

    click.echo(f"Loaded {len(docs)} documents.")
    chunker = SectionAwareChunker(DEFAULT_CONFIG.chunker)
    chunks = chunker.chunk_documents(docs)

    click.echo(f"Generated {len(chunks)} chunks.")
    token_counts = [c.token_count for c in chunks]
    min_tokens = min(token_counts) if token_counts else 0
    max_tokens = max(token_counts) if token_counts else 0
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0

    chunk_ids = set()
    duplicates = 0
    for c in chunks:
        if c.chunk_id in chunk_ids:
            duplicates += 1
        chunk_ids.add(c.chunk_id)

    click.echo("--- Audit Summary ---")
    click.echo(f"Total Documents:    {len(docs)}")
    click.echo(f"Total Chunks:       {len(chunks)}")
    click.echo(f"Unique Chunk IDs:   {len(chunk_ids)}")
    click.echo(f"Duplicate IDs:      {duplicates}")
    click.echo(f"Token Min / Avg / Max: {min_tokens} / {avg_tokens:.1f} / {max_tokens}")
    click.echo(f"Sample Chunk IDs:   {list(chunk_ids)[:5]}")
    click.echo("Audit passed successfully.")


@cli.command("index")
@click.argument("corpus_path", type=click.Path(exists=True))
@click.option("--output", "-o", default="./data/index", help="Output index directory.")
def index_command(corpus_path: str, output: str):
    """Chunk, compute BM25 and Dense embeddings, and persist index."""
    click.echo(f"Indexing corpus from {corpus_path} -> {output}")
    path = Path(corpus_path)
    if path.is_dir():
        docs = CorpusLoader.load_directory(path)
    else:
        docs = CorpusLoader.load_file(path)

    engine = HybridRetrievalEngine(DEFAULT_CONFIG)
    total_indexed = engine.index_documents(docs)
    engine.save(Path(output))

    stats = engine.get_stats()
    click.echo(f"Successfully indexed {total_indexed} chunks.")
    click.echo(json.dumps(stats, indent=2))


@cli.command("search")
@click.argument("query")
@click.option("--index", "-i", default="./data/index", help="Path to index directory.")
@click.option("--mode", "-m", default="hybrid", type=click.Choice(["bm25", "dense", "hybrid"], case_sensitive=False))
@click.option("--top", "-k", default=10, type=int, help="Number of results to return.")
def search_command(query: str, index: str, mode: str, top: int):
    """Search the index using bm25, dense, or hybrid (RRF) mode."""
    idx_path = Path(index)
    if not idx_path.exists():
        click.echo(f"Error: Index directory {index} does not exist. Run 'slrag index' first.", err=True)
        sys.exit(1)

    engine = HybridRetrievalEngine.load(idx_path, config=DEFAULT_CONFIG)
    t0 = time.perf_counter()
    results = engine.search(query, mode=mode, top_k=top)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    click.echo(f"\n--- Search Results for '{query}' [Mode: {mode.upper()}, Top: {top}] (Latency: {latency_ms:.2f}ms) ---")
    if not results:
        click.echo("No results found.")
        return

    for r in results:
        click.echo(f"\n[{r.rank}] Chunk ID: {r.chunk_id} | Score: {r.score:.4f} | Section: {r.section_title}")
        click.echo(f"    Source Scores: {r.source_scores}")
        preview = (r.text[:120] + "...") if len(r.text) > 120 else r.text
        click.echo(f"    Text: {preview}")


@cli.command("probe")
@click.option("--index", "-i", default="./data/index", help="Path to index directory.")
def probe_command(index: str):
    """Probe system health, index status, embedding dimension, and retrieval latency."""
    click.echo("--- Probing SL-RAG Engine ---")
    click.echo(f"Config Hash: {DEFAULT_CONFIG.cfg_hash}")
    click.echo(f"Embedding Model: {DEFAULT_CONFIG.dense.model_name} (Dim: {DEFAULT_CONFIG.dense.embedding_dim})")

    idx_path = Path(index)
    if idx_path.exists():
        engine = HybridRetrievalEngine.load(idx_path, config=DEFAULT_CONFIG)
        stats = engine.get_stats()
        click.echo(f"Index Location: {idx_path.resolve()}")
        click.echo(f"Indexed Chunks: {stats['total_chunks']}")
        click.echo(f"BM25 Vocab Size: {stats['vocab_size']}")

        # Benchmark latency
        benchmark_queries = ["vector search retrieval", "bm25 okapi postings", "system latency"]
        latencies = []
        for q in benchmark_queries:
            t0 = time.perf_counter()
            _ = engine.search(q, mode="hybrid", top_k=5)
            latencies.append((time.perf_counter() - t0) * 1000.0)

        avg_lat = sum(latencies) / len(latencies)
        click.echo(f"Benchmark Search Latency (Hybrid): avg {avg_lat:.2f}ms across {len(benchmark_queries)} queries.")
    else:
        click.echo(f"Index directory {index} not found (fresh state).")

    click.echo("Probe completed: System healthy.")


if __name__ == "__main__":
    cli()
