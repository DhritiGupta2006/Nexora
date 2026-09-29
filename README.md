# SL-RAG: Streaming Hybrid Retrieval-Augmented Generation Engine

A production-grade, low-latency streaming RAG system built with deterministic corpus normalization, hybrid Okapi BM25 + dense neural retrieval (BAAI/bge-small), zero-loss async telemetry bus, session-isolated stream gateway, and a fail-closed claim verification pipeline.

---

## Architecture Overview

```
+----------------------------------------------------------------------------------------------------+
|                                      SL-RAG Streaming Pipeline                                     |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [ Ingest / Loader ] ---> [ Section-Aware Chunker ] ---> [ Doc_ID§Section Stable Deterministic IDs]|
|                                                                    |                               |
|                               +------------------------------------+------------------------------+|
|                               |                                                                   ||
|                               v                                                                   v|
|                    [ BM25 Okapi Index ]                                             [ Dense BGE-Small 384d ]
|                    (Vocab, Postings, IDF)                                           (Unit L2 Normalized)   |
|                               |                                                                   ||
|                               +------------------------------------+------------------------------+|
|                                                                    |                               |
|                                                                    v                               |
|                                                   [ Reciprocal Rank Fusion (RRF) ]                 |
|                                                                    |                               |
|                                                                    v                               |
|  [ WebSocket / Client ] ---> [ Reorder Buffer ] ---> [ Gateway Normalizer ] ---> [ Instrumented Search ]
|                                                                                        |           |
|                                                                                        v           |
|                                                                            [ Sufficiency Gate ]    |
|                                                                            (dense>=0.55, cov>=0.5) |
|                                                                                        |           |
|                                                                                        v           |
|                                                                            [ Claim Drafter ]       |
|                                                                            (Enum-Constrained IDs)  |
|                                                                                        |           |
|                                                                                        v           |
|                                                                            [ Fail-Closed Verifier ]|
|                                                                            (5 Grounding Checks)    |
|                                                                                        |           |
|                                                                                        v           |
|  [ JSONL + WS Telemetry ] <--- [ Zero-Loss Telemetry Bus ] <---------------- [ Versioned Ledger v1 ]
|                                                                                        |           |
|                                                                                        v           |
|  [ Client Stream ] <------------------------------------------------------- [ AnswerDelta Stream ] |
+----------------------------------------------------------------------------------------------------+
```

---

## Key Features

### Phase 1: Foundation, Corpus Ingestion & Hybrid Retrieval
- **Reproducible Chunk Identifiers**: Generates deterministic `Doc_ID§Section` IDs that remain consistent across runs and indexing cycles.
- **Section-Aware Chunker**: Respects logical document headings and preserves section boundaries (300–500 tokens).
- **Okapi BM25 Index**: Complete implementation with vocabulary mapping, IDF table, stored postings, and term frequency saturation.
- **Dense Embedding Engine**: BAAI/bge-small compatible 384-dimensional normalized vector indexing with cosine similarity.
- **Reciprocal Rank Fusion (RRF)**: Merges BM25 and dense rankings with tie-breaking and rank weighting.
- **`slrag` CLI**: Commands for `audit`, `index`, `search`, and `probe`.

### Phase 2: Event Contracts, Telemetry Bus & Stream Gateway
- **Frozen Pydantic v2 Contracts**: Immutable schemas with configuration hashing (`cfg_hash`), session IDs, and sequence tracking.
- **Zero-Loss Telemetry Bus**: Dual-target async emitter logging to disk JSONL and broadcasting to active WebSocket subscribers.
- **Stream Gateway**: Schema key alias normalization, cumulative/delta text merging, and sequence reorder buffering.
- **Session Registry**: Lazy session instantiation, per-session async locks for concurrency isolation, and idle session reaper.
- **Trace Coverage Checker**: End-of-turn lifecycle validator ensuring trace completeness.
- **FastAPI Service**: Endpoints for `/health`, `/ws/stream`, `/ws/telemetry`, `/metrics`, and `/debug/search`.

### Phase 3: Grounded Answer Pipeline
- **Qwen2.5-3B-Instruct LLM Wrapper**: Token accounting (`tokens_in`, `tokens_out`) and generation cost calculations.
- **Sufficiency Gate**: Enforces `dense_top1 >= 0.55` and `coverage >= 0.50` prior to drafting claims.
- **Enum-Constrained Claim Drafter**: Constrains citations exclusively to the active retrieved chunk set.
- **Fail-Closed Verifier**: Runs 5 independent verification checks:
  1. *Lexical Check*: Token overlap against cited text.
  2. *Semantic Check*: Embedding similarity between claim and chunk.
  3. *Coreference Check*: Entity grounding for pronouns.
  4. *Hallucinated ID Check*: Rejects any doc ID outside the retrieved set.
  5. *Consistency Check*: Rejects claims contradicting the ledger or context.
- **Claim Ledger v1**: Monotonically incrementing versioned store tracking verified claims across turns.
- **Batch Turn Engine**: Coordinates retrieval, gating, verification, streaming deltas, and turn summaries.

---

## CLI Usage

### 1. Audit Corpus
```bash
./bin/slrag audit data/sample_corpus.json
```

### 2. Index Corpus
```bash
./bin/slrag index data/sample_corpus.json --output data/index
```

### 3. Search Index
```bash
./bin/slrag search "surface code physical qubits error threshold" --index data/index --mode hybrid --top 3
```

### 4. Probe System
```bash
./bin/slrag probe --index data/index
```

---

## Running Tests

Run the full suite of unit and integration tests:

```bash
PYTHONPATH=. pytest tests/ -v
```

All 19 test cases across all three phases pass cleanly.
