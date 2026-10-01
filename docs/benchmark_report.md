# SL-RAG Benchmark Report

## Setup

| Item | Value |
|---|---|
| Configuration | `config.yaml`, `frozen: true`, `cfg_hash 90e68e6053d494aa` (stamped in `out/summary.json` and `out/final_experiments.json`) |
| Split | test: 39 scenarios + 8 late-detail sessions = 47 sessions, 55 turns (seed 13, temperature 0) |
| Calibration | controller thresholds tuned on the tune split only (36 + 7 sessions), then frozen |
| Corpus | 24 synthetic Nexora documents (93 sections) plus the 8-section sample corpus: 101 indexed chunks |
| LLM | `heuristic` backend (deterministic stand-in drafter, no model server) |
| Timing | virtual replay clock (retrieval 120 ms, draft 350 ms, verify 15 ms, chunk interval 200 ms): relative, not hardware latency |
| Cost | token estimates × configured prices ($0.00015 / $0.0006 per 1k in / out): notional |
| Baselines | **B1**: hybrid retrieval and verifier, but batch (retrieves only at utterance end), no planner, restarts on a late detail. **B0**: as B1 but dense-only and without the verifier. |

Reproduce with:
- `python -m slrag.cli replay eval/scenarios --split test --out out/ours_test.jsonl`, which writes `out/summary.json` and `out/report.md`;
- `python scripts/run_experiments.py`, which writes `out/final_experiments.json`.

## 1. Metrics: Ours vs baselines (test split)

| # | Metric | Ours | B1 | B0 |
|---|---|---|---|---|
| 1 | recall@5 | **0.872** | 0.731 | 0.538 |
| 2 | recall@10 | **0.926** | 0.846 | 0.679 |
| 3 | groundedness (verifier score) | **0.975** | 0.956 | n/a (no verifier) |
| 4 | hallucinated-ID rate | **0.000** | 0.000 | 0.000 |
| 5 | TTFT p50 (virtual ms) | **388** | 485 | 485 |
| 6 | TTFT p95 (virtual ms) | **490** | 590 | 590 |
| 7 | cost per turn (notional $) | 0.000420 | 0.000181 | **0.000158** |
| 8 | early-retrieval rate | **0.950** | 0.000 | 0.000 |
| 9 | false-trigger rate | 0.000 | 0.000 | 0.000 |
| 10 | sub-intent recall | **0.918** | 0.607 | 0.508 |
| 11 | over-fragmentation | 0.077 | **0.000** | **0.000** |
| 12 | suppression precision / recall | 0.615 / 1.000 | **0.800** / 1.000 | 0.500 / 1.000 |
| 13 | uncertainty precision / recall | 0.320 / 1.000 | **0.800** / 1.000 | 0.500 / 1.000 |
| 14 | claim preservation on late details | **1.000** | n/a (restarts) | n/a (restarts) |
| 15 | refinement savings, turn-2 retrieval calls (A4) | **56.3% fewer** (7 vs 16) | baseline | n/a |
| 16 | trace coverage | **1.000** | 0.952 | 0.833 |

Where Ours is worse than the baselines:
- It costs 2.3× as much per turn as B1, because of speculation and pre-drafting.
- It over-fragments 7.7% of single intents (failure 3).
- It has lower suppression and uncertainty precision than B1 (failure 2), because it splits more and so flags more sub-intents.

## 2. Gates G1–G6 (test split, `out/summary.json`)

| Gate | Condition | Measured | Status |
|---|---|---|---|
| G1 recall improvement | recall@10 Ours ≥ B1 | 0.926 ≥ 0.846 | ✅ PASS |
| G2 early retrieval | early_retrieval_rate ≥ 0.80 | 0.950 | ✅ PASS |
| G3 groundedness preservation | groundedness Ours ≥ B1 | 0.975 ≥ 0.956 | ✅ PASS |
| G4 grounding | groundedness ≥ 0.85 and hallucinated-ID rate = 0 | 0.975, 0.000 | ✅ PASS |
| G5 late-detail refinement | preservation = 1.0, restarts = 0, lineage complete | 1.000, 0, 1.000 | ✅ PASS |
| G6 trace coverage | coverage = 1.0 | 1.000 | ✅ PASS |

The frozen-config replay reproduced the pre-freeze `summary.json` exactly: no metric changed.

## 3. Ablations A1–A5 (`out/final_experiments.json`)

Each arm runs the full "ours" pipeline with exactly one setting changed.

### A1: Retrieval (hybrid vs dense-only vs BM25-only)

| Arm | recall@5 | recall@10 | sub-intent recall | groundedness | uncertainty P |
|---|---|---|---|---|---|
| hybrid (shipped) | 0.872 | 0.926 | 0.918 | 0.975 | 0.320 |
| dense only | 0.649 | 0.809 | 0.787 | 0.986 | 0.222 |
| BM25 only | **0.936** | **0.989** | **0.984** | 0.937 | **0.471** |

**Finding.** BM25 alone retrieves better than the shipped hybrid. The dense side is a hashed n-gram projection, not a neural embedder (see failure 1). Fusing it in still beats dense-only, but dilutes BM25's exact-match hits.

BM25-only arm has lower groundedness (0.937). More answers get drafted, and the verifier's semantic check uses the same weak embedder.

The weights were not retuned on the test split. Any change needs a tune-split recalibration, then a refreeze.

### A2: Controller (eager vs rules_only vs cascade vs llm_only)

| Arm | early retrieval | false trigger | wasted speculation | cache hit | TTFT p50 / p95 | cost / turn | recall@10 |
|---|---|---|---|---|---|---|---|
| eager | 0.888 | 0.000 | 0.313 | 0.392 | 385 / 490 | 0.000314 | 0.936 |
| rules_only | 0.950 | 0.000 | 0.223 | 0.458 | 388 / 490 | 0.000420 | 0.926 |
| cascade (shipped) | 0.950 | 0.000 | 0.223 | 0.458 | 388 / 490 | 0.000420 | 0.926 |
| llm_only | 0.950 | 0.000 | 0.223 | 0.458 | 388 / 490 | 0.000420 | 0.926 |

**Finding.** cascade, rules_only and llm_only are identical, and all 290 controller decisions in the test run came from tier T1:
- T0 and T2 only engage once a session already has an answer.
- In `llm_only` mode, the heuristic T2 classifier answers RETRIEVE, which hands the decision to T1.

The cascade's T0/T2 tiers are therefore unmeasured by this harness. Their effect is visible only on live multi-turn sessions, such as the presentation turns in the UI.

Eager dispatch wastes more speculation (0.313 vs 0.223). It also triggers early on fewer turns: eager queries are often too partial to count as covering the gold evidence.

### A3: Speculation (off vs retrieval_only vs full)

| Arm | TTFT p50 / p95 | cost / turn | groundedness | early retrieval | pre-draft tokens wasted |
|---|---|---|---|---|---|
| off | 490 / 490 | 0.000323 | 0.974 | 0.000 | n/a |
| retrieval_only | **385** / 490 | **0.000316** | 0.975 | 0.950 | n/a |
| full (shipped) | 388 / 490 | 0.000420 | 0.975 | 0.950 | 18,075 (63.0%) |

**Finding.** Early retrieval is where the latency win comes from: 105 ms off the p50. Pre-drafting (`full`) does not improve TTFT on this split:
- Of 29 pre-drafts, 13 stood, 0 were refined and 16 were redone.
- Only 34.5% were ready before the utterance ended.
- It adds about 33% to cost per turn.

Groundedness is unchanged (parity holds). `retrieval_only` is the better operating point on these numbers. The shipped config keeps `full` because the config was frozen before this measurement.

### A4: Late-detail refinement (delta) vs restart

| | turn-2 retrieval calls | turn-2 tokens |
|---|---|---|
| refinement (ours) | **7** | 22,085 |
| restart (B1) | 16 | **5,670** |

- Over 8 sessions, refinement makes 56.3% fewer retrieval calls and keeps every unaffected claim (preservation 1.0).
- It uses **3.9× more tokens** (failure 4).
- Delta-planner relation accuracy is 1.000, affected-sub-intent accuracy 0.875, and delta recall@5 0.875.

### A5: Fail-closed verifier (on vs off)

| Arm | groundedness | emitted claims | supported on post-hoc re-check | hallucinated-ID rate |
|---|---|---|---|---|
| on (shipped) | 0.975 | 464 | 464 (100%) | 0.000 |
| off | n/a | 139 | 137 (98.6%) | 0.000 |

With the verifier on, every emitted claim survives the post-hoc re-check. With it off, 2 claims that fail the rules would have reached the user.

**Caveat.** This arm is not a clean comparison. With `enable_verifier: false`, the engine emitted answers in only 18 of the 38 answered turns, because unverified claims are recorded but not streamed. The off arm therefore under-reports what an unfiltered system would say. It is reported as measured.

## 4. Failure analysis (real failures from the test run)

### Failure 1: Hybrid fusion buries exact keyword hits (`presentation_03`, `compound_10`, `late_10`)

- **Expected.** `presentation_03` ("Summarize how Nexora encrypts data in transit and at rest.") should retrieve `nx-security§encryption` and answer it.
- **Actual.** The gold chunk is BM25 rank 1, dense rank 28 and hybrid rank 7, so it falls outside the 4-chunk evidence quota. The sufficiency gate saw coverage 0.33 and suppressed the turn as insufficient evidence.
- **Same pattern elsewhere.**

  | Scenario | Sub-query | BM25 rank | Hybrid rank | Outcome |
  |---|---|---|---|---|
  | `compound_10` | "how do I set up the HubSpot integration?" | 10 | 15 | — |
  | `late_10` | "How do LSM trees handle writes?" | 1 | 27 | suppressed |
- **Root cause.** This is the retrieval layer: `slrag/retrieval/dense.py` with RRF in `fusion.py`.
  - The "dense" embedder hashes word and character n-grams; it is not a neural model, so its ranking is close to noise for paraphrased content.
  - RRF with weights 0.6 dense / 0.4 BM25 lets that noise outvote a confident BM25 rank 1.
  - A1 confirms it: BM25-only recall@10 is 0.989.
- **Mitigation.** Put a real embedding model behind `DenseIndex`, or re-weight RRF towards BM25, recalibrated on the tune split. Not done here: the config is frozen and the test split must not be used for tuning.

### Failure 2: Uncertainty flags on answerable sub-intents (uncertainty precision 0.32)

- **Expected.** Answerable sub-intents are answered without an uncertainty flag.
- **Actual.** 25 sub-intents were flagged, and only the 8 truly unanswerable ones were right (precision 8 / 25 = 0.32). The 17 false flags were:
  - 5 answerable sub-intents suppressed for insufficient evidence, mostly through failure 1 (`presentation_03`, `presentation_06`, `presentation_07`, `compound_08`, `late_10:t1`);
  - 12 answered but marked "uncertain", including:

  | Scenario | Query coverage |
  |---|---|
  | `compound_06` sub_1 | 0.667 |
  | `compound_07` sub_1 | 0.500 |
  | `compound_25` | 0.500 and 0.667 |
  | `single_early_06` | 0.571 |
  | `late_04:t1` | 0.600 |
- **Root cause.** This is the suppression gate (`slrag/pipeline/suppression.py`). It flags any answer whose query coverage falls in the band [0.50, 0.70) (`uncertain_band_low/high` in `slrag/config.py`). That band was never calibrated: most correctly answered sub-queries have coverage between 0.5 and 0.67, so the band catches them. Recall is 1.0, so no truly unanswerable part slips through. The cost is noise.
- **Mitigation.** Calibrate the band on the tune split, or narrow it to [0.50, 0.55). Left as is, because the config is frozen.

### Failure 3: Over-fragmentation into a pronoun-only sub-query (`compound_26`)

- **Expected.** Two sub-intents:
  1. "How many employees does Nexora have and where are its offices?" (one chunk: `nx-company§team-offices`);
  2. "how does the Salesforce sync retry failed records?"
- **Actual.** The planner split the first intent at "and", producing "How many employees does Nexora have" and the pronoun-only "where are its offices?".
  - Neither half retrieved the gold chunk in the top 10. "Nexora" is in almost every document, so it carries little IDF weight, and "its" carries none.
  - Hybrid ranks were 46 and 15. BM25 ranks were 5 and 1, so fusion (failure 1) made it worse.
  - Both halves were answered with an uncertainty flag. This is one of the over-fragmentation cases (rate 0.077).
- **Root cause.** This is the planner's coordinator split (`slrag/plan/splitter.py`). It splits a clause on "and" even when the second part has no subject of its own, and it does not carry the antecedent ("Nexora") into the pronoun clause.
- **Mitigation.** Do not split when the right-hand clause starts with a pronoun subject ("its", "it", "they"), or substitute the antecedent before retrieval. Left: this is a planner change that needs a tune-split re-run.

### Failure 4: Refinement spends more tokens than restarting (A4)

- **Expected.** Refining only the affected claims should be cheaper than restarting.
- **Actual.** Turn-2 refinement used 22,085 tokens vs 5,670 for restart (3.9×), although it made 7 vs 16 retrieval calls.
- **Root cause.** This is the Phase 7 refinement path: the delta planner (`slrag/plan/delta_planner.py`) and the rewriter (`slrag/answer/rewriter.py`), driven from `slrag/engine/turn_engine.py`. A refinement turn makes two JSON LLM calls; restart makes one draft from 4 chunks (about 709 tokens per turn). Measured over the 8 sessions:

  | Call | Tokens | Largest parts |
  |---|---|---|
  | delta planner | 8,025 | 5,122: every session claim (first 20 words each), serialized as JSON |
  | rewriter | 14,060 | 4,199 new evidence, 4,003 claims of the affected sub-intents, 3,573 JSON schema |

  The JSON schemas embedded in both prompts account for 4,617 tokens, 21% of the total. With the heuristic backend, tokens are estimated from prompt length, so this is a property of the prompt design, not of a model.
- **Mitigation.**
  - Drop the schema text from the prompt when the backend enforces structured output itself (Ollama's `format` already does).
  - Give the delta planner sub-intent summaries instead of every claim.
  - Cap rewriter evidence at the chunks not already cited.

  Left for a follow-up.

## 5. Compliance

`python scripts/compliance_audit.py` passes all six checks: corpus isolation, no hardcoding, no precomputation, session isolation, parsimony and prompts. It writes `out/compliance.json`.

The no-precomputation check includes a replay of the full test split with every gold label stripped: 729 engine decisions were identical. The labels annotate telemetry for the metrics only.

## 6. What this report does not claim

- Absolute latency on any hardware: all latency is virtual time.
- Real-dollar cost.
- "Zero hallucination" in general. Groundedness is the verifier's rule-based score, and no human-labelled sample or LLM judge was run.
- Performance with a neural embedder or with the Ollama backend: neither was measured.
- Anything about a private held-out set.
