"""Author 75 deterministic scenarios with real semantic chunk IDs and seed-13 stratified splitting."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple


def generate_75_scenarios() -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []

    # 1. 30 Compound Scenarios
    compound_pairs = [
        ("What is the core Nexora architectural layout?", ["doc-nexora-arch-c0"],
         "how does hybrid retrieval fuse dense and sparse results?", ["doc-retrieval-hybrid-c0"]),
        ("Explain the gateway ingress buffering mechanism", ["doc-nexora-arch-c1"],
         "what is the dense vector similarity threshold?", ["doc-retrieval-hybrid-c1"]),
        ("How does the ledger maintain claim state across turns?", ["doc-nexora-arch-c2"],
         "what telemetry events are emitted on turn start?", ["doc-telemetry-contracts-c0"]),
        ("What is the role of split-plane gateway architecture?", ["doc-nexora-arch-c0"],
         "how is TTFT calculated across latency tracing spans?", ["doc-telemetry-contracts-c1"]),
        ("How does the gateway normalizer handle packet reordering?", ["doc-nexora-arch-c1"],
         "what format does the telemetry JSONL sink require?", ["doc-telemetry-contracts-c2"]),
        ("How does the claim ledger enforce session isolation?", ["doc-nexora-arch-c2"],
         "how does RRF combine BM25 and vector scores?", ["doc-retrieval-hybrid-c0"]),
        ("Describe the Nexora low-latency streaming RAG design", ["doc-nexora-arch-c0"],
         "what are the memory footprints of dense indices?", ["doc-retrieval-hybrid-c1"]),
        ("What is the packet reordering window size in the gateway?", ["doc-nexora-arch-c1"],
         "how does the telemetry bus dispatch events?", ["doc-telemetry-contracts-c0"]),
        ("How are claims invalidated in the ledger state?", ["doc-nexora-arch-c2"],
         "where are span measurement points placed?", ["doc-telemetry-contracts-c1"]),
        ("Explain split-plane routing in Nexora architecture", ["doc-nexora-arch-c0"],
         "what fields are non-nullable in telemetry records?", ["doc-telemetry-contracts-c2"]),
        ("How does the gateway interface with the streaming engine?", ["doc-nexora-arch-c1"],
         "what is the dense embedding dimension threshold?", ["doc-retrieval-hybrid-c1"]),
        ("How does session isolation protect concurrent turn state?", ["doc-nexora-arch-c2"],
         "what is the sparse BM25 weight in hybrid fusion?", ["doc-retrieval-hybrid-c0"]),
        ("What is the foundational Nexora architecture component?", ["doc-nexora-arch-c0"],
         "how are telemetry spans structured in a tree hierarchy?", ["doc-telemetry-contracts-c1"]),
        ("Describe ingress buffering normalizer contracts", ["doc-nexora-arch-c1"],
         "how does the event bus handle subscriber backpressure?", ["doc-telemetry-contracts-c0"]),
        ("How does the claim ledger reconcile partial draft outputs?", ["doc-nexora-arch-c2"],
         "what serialization is used for telemetry JSONL?", ["doc-telemetry-contracts-c2"]),
        ("How do the gateway and core pipeline interact?", ["doc-nexora-arch-c0"],
         "how are reciprocal rank fusion ranks calculated?", ["doc-retrieval-hybrid-c0"]),
        ("Explain how out-of-order packets are reassembled", ["doc-nexora-arch-c1"],
         "what is the vector quantization strategy?", ["doc-retrieval-hybrid-c1"]),
        ("How are verified claims appended to the ledger?", ["doc-nexora-arch-c2"],
         "what event types are recognized by the telemetry bus?", ["doc-telemetry-contracts-c0"]),
        ("What design principles govern the low-latency streaming pipeline?", ["doc-nexora-arch-c0"],
         "how are latency tracing spans closed?", ["doc-telemetry-contracts-c1"]),
        ("What happens when normalizer buffers experience overflow?", ["doc-nexora-arch-c1"],
         "how does JSONL sink serialize nested objects?", ["doc-telemetry-contracts-c2"]),
        ("How does the ledger prevent cross-talk between turns?", ["doc-nexora-arch-c2"],
         "how is BM25 term frequency scored in hybrid search?", ["doc-retrieval-hybrid-c0"]),
        ("Describe the split-plane data and control architecture", ["doc-nexora-arch-c0"],
         "how does cosine similarity evaluate dense candidates?", ["doc-retrieval-hybrid-c1"]),
        ("How does ingress packet validation ensure payload integrity?", ["doc-nexora-arch-c1"],
         "how does telemetry publish asynchronous event streams?", ["doc-telemetry-contracts-c0"]),
        ("How are multi-turn dialogue claims indexed in the ledger?", ["doc-nexora-arch-c2"],
         "how does TTFT measurement capture first token latency?", ["doc-telemetry-contracts-c1"]),
        ("What architectural layers comprise the Nexora gateway?", ["doc-nexora-arch-c0"],
         "what timestamp formatting is used in telemetry JSONL?", ["doc-telemetry-contracts-c2"]),
        ("Explain gateway packet reordering threshold boundaries", ["doc-nexora-arch-c1"],
         "how does RRF blend dense rank with sparse rank?", ["doc-retrieval-hybrid-c0"]),
        ("How are claim ledgers persisted across session lifetimes?", ["doc-nexora-arch-c2"],
         "how does dense index quantization reduce memory?", ["doc-retrieval-hybrid-c1"]),
        ("Summarize core Nexora streaming RAG architecture", ["doc-nexora-arch-c0"],
         "what telemetry contracts govern event schemas?", ["doc-telemetry-contracts-c0"]),
        ("How does the ingress gateway buffer incoming token chunks?", ["doc-nexora-arch-c1"],
         "how are span tree parent IDs propagated?", ["doc-telemetry-contracts-c1"]),
        ("What claim attributes are recorded in the ledger?", ["doc-nexora-arch-c2"],
         "how does the JSONL exporter flush telemetry batches?", ["doc-telemetry-contracts-c2"]),
    ]
    for idx, (q1, g1, q2, g2) in enumerate(compound_pairs, start=1):
        scenarios.append({
            "scenario_id": f"compound_{idx:02d}",
            "category": "compound",
            "query": f"{q1} and {q2}",
            "sub_intents": [
                {"id": "sub_1", "query": q1, "gold_chunk_ids": g1},
                {"id": "sub_2", "query": q2, "gold_chunk_ids": g2}
            ],
            "is_unanswerable": False
        })

    # 2. 15 Single-Early Scenarios
    single_early_queries = [
        ("Explain the token-paced drafter streaming engine design.", ["doc-streaming-engine-c0"]),
        ("How does speculative draft generation accelerate streaming?", ["doc-streaming-engine-c0"]),
        ("Describe the token pacing policy for real-time streaming.", ["doc-streaming-engine-c0"]),
        ("How does flow-control backpressure prevent client socket flooding?", ["doc-streaming-engine-c1"]),
        ("What threshold triggers socket backpressure in the streaming engine?", ["doc-streaming-engine-c1"]),
        ("Explain streaming buffer allocation during high-load flow control.", ["doc-streaming-engine-c1"]),
        ("How does the streaming engine handle abrupt client socket disconnects?", ["doc-streaming-engine-c2"]),
        ("What cleanup occurs upon client interruption during active drafting?", ["doc-streaming-engine-c2"]),
        ("Describe graceful degradation when a streaming consumer lags.", ["doc-streaming-engine-c2"]),
        ("How does speculative drafting interact with the token generator?", ["doc-streaming-engine-c0"]),
        ("What backpressure signals are exchanged between drafter and socket?", ["doc-streaming-engine-c1"]),
        ("How are partial responses flushed when client cancels connection?", ["doc-streaming-engine-c2"]),
        ("Explain the internal loop of the token-paced streaming drafter.", ["doc-streaming-engine-c0"]),
        ("How is buffer capacity managed under flow-control backpressure?", ["doc-streaming-engine-c1"]),
        ("What error state is emitted when client disconnects unexpectedly?", ["doc-streaming-engine-c2"]),
    ]
    for idx, (q, g) in enumerate(single_early_queries, start=1):
        scenarios.append({
            "scenario_id": f"single_early_{idx:02d}",
            "category": "single-early",
            "query": q,
            "sub_intents": [
                {"id": "sub_1", "query": q, "gold_chunk_ids": g}
            ],
            "is_unanswerable": False
        })

    # 3. 15 Presentation Scenarios
    presentation_queries = [
        ("Summarize how hybrid retrieval fuses BM25 and dense indices via RRF.", ["doc-retrieval-hybrid-c0"]),
        ("Summarize dense index vector quantization and memory footprints.", ["doc-retrieval-hybrid-c1"]),
        ("Summarize the event bus publish-subscribe telemetry architecture.", ["doc-telemetry-contracts-c0"]),
        ("Summarize latency tracing spans and TTFT measurement hierarchy.", ["doc-telemetry-contracts-c1"]),
        ("Summarize telemetry JSONL sink serialization format specifications.", ["doc-telemetry-contracts-c2"]),
        ("Summarize the RRF reciprocal rank fusion formula and scoring weights.", ["doc-retrieval-hybrid-c0"]),
        ("Summarize cosine similarity evaluation criteria for dense vectors.", ["doc-retrieval-hybrid-c1"]),
        ("Summarize telemetry bus event taxonomy and subscription handling.", ["doc-telemetry-contracts-c0"]),
        ("Summarize span tree propagation rules for latency monitoring.", ["doc-telemetry-contracts-c1"]),
        ("Summarize telemetry record schema validation and nullability rules.", ["doc-telemetry-contracts-c2"]),
        ("Summarize advantages of combining sparse BM25 with dense retrieval.", ["doc-retrieval-hybrid-c0"]),
        ("Summarize index compaction techniques for vector memory footprints.", ["doc-retrieval-hybrid-c1"]),
        ("Summarize async telemetry event publishing performance benefits.", ["doc-telemetry-contracts-c0"]),
        ("Summarize TTFT benchmark collection points across pipeline stages.", ["doc-telemetry-contracts-c1"]),
        ("Summarize telemetry file rotation and batch flush policies in JSONL.", ["doc-telemetry-contracts-c2"]),
    ]
    for idx, (q, g) in enumerate(presentation_queries, start=1):
        scenarios.append({
            "scenario_id": f"presentation_{idx:02d}",
            "category": "presentation",
            "query": q,
            "sub_intents": [
                {"id": "sub_1", "query": q, "gold_chunk_ids": g}
            ],
            "is_unanswerable": False
        })

    # 4. 15 Unanswerable Scenarios
    unanswerable_queries = [
        "What was the stock market trading volume of Nexora in 1920?",
        "What are the weather conditions on Mars right now?",
        "Who won the soccer world cup final in the year 1850?",
        "What is the secret baking recipe for Nexora brand chocolate cookies?",
        "Which airline operates daily direct flights from Tokyo to Atlantis?",
        "What is the average lifespan of a wild dragon in medieval folklore?",
        "How many electric cars were manufactured in California during 1880?",
        "What is the municipal tax rate of the floating city of El Dorado?",
        "Who was the prime minister of Antarctica during the nineteenth century?",
        "What is the current price of interstellar warp drive engines?",
        "Which baseball team won the championship on the moon in 1969?",
        "What is the official currency exchange rate of Narnia lion coins?",
        "How many coffee cups were consumed during the signing of Magna Carta?",
        "What is the repair manual for time-travel tachyon flux capacitors?",
        "Which company invented underwater supersonic passenger trains in 1910?"
    ]
    for idx, q in enumerate(unanswerable_queries, start=1):
        scenarios.append({
            "scenario_id": f"unanswerable_{idx:02d}",
            "category": "unanswerable",
            "query": q,
            "sub_intents": [
                {"id": "sub_1", "query": q, "gold_chunk_ids": []}
            ],
            "is_unanswerable": True
        })

    return scenarios


def make_stratified_split(
    scenarios: List[Dict[str, Any]],
    seed: int = 13
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rng = random.Random(seed)
    categories: Dict[str, List[Dict[str, Any]]] = {}
    for s in scenarios:
        categories.setdefault(s["category"], []).append(s)

    tune_set: List[Dict[str, Any]] = []
    test_set: List[Dict[str, Any]] = []

    for cat in sorted(categories.keys()):
        items = list(categories[cat])
        rng.shuffle(items)
        split_idx = len(items) // 2
        tune_set.extend(items[:split_idx])
        test_set.extend(items[split_idx:])

    tune_set.sort(key=lambda s: s["scenario_id"])
    test_set.sort(key=lambda s: s["scenario_id"])
    return tune_set, test_set


def write_split_files(base_dir: str = "eval/scenarios") -> None:
    p = Path(base_dir)
    p.mkdir(parents=True, exist_ok=True)
    scenarios = generate_75_scenarios()
    tune_set, test_set = make_stratified_split(scenarios, seed=13)

    tune_path = p / "tune.jsonl"
    with open(tune_path, "w", encoding="utf-8") as f:
        for s in tune_set:
            f.write(json.dumps(s) + "\n")

    test_path = p / "test.jsonl"
    with open(test_path, "w", encoding="utf-8") as f:
        for s in test_set:
            f.write(json.dumps(s) + "\n")
