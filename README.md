# SL-RAG: Streaming Live RAG

SL-RAG answers questions about a fixed document corpus while the user is still speaking or typing. Transcript chunks stream in over a WebSocket, and a retrieval controller decides on every chunk whether there is enough meaning to retrieve yet. Multi-part questions are split into sub-queries, and each is retrieved as soon as its clause is complete. When the utterance ends, the evidence is usually already there, so the first grounded sentence arrives sooner (test-split TTFT p50 388 ms vs 485 ms for a retrieve-at-the-end baseline, in virtual replay time).

Answers are built only from retrieved evidence. Every claim cites a `doc§section` chunk, and a fail-closed verifier drops any claim it cannot ground in the chunk it cites (groundedness 0.975, 0 hallucinated ids). Parts of a question the corpus cannot answer are reported as uncertain instead of guessed. If the user adds a constraint later ("assume we're on the Enterprise plan"), only the affected claims are revised, and the rest of the answer is preserved unchanged. Every decision is emitted as telemetry, and a trace UI shows it live.

## Quick start

```bash
make model && make up
```

Then open **http://localhost:8000/ui/trace** and sign in as **admin / slrag**.

- `make model` starts the Ollama service and pulls `qwen2.5:3b` into its volume. This is only needed for the real-LLM mode, but harmless otherwise.
- `make up` builds and starts the app with `docker compose up --build`.
- Without `make`, for example on Windows, run the same steps directly:
  ```bash
  docker compose up -d ollama && docker compose exec ollama ollama pull qwen2.5:3b
  docker compose up --build
  ```
- Without Docker:
  ```bash
  pip install -e . && python -m uvicorn slrag.server.app:app --port 8000
  ```

In the UI, pick a scenario under **New Run** and press **Run** to replay it. Or drop a telemetry `.jsonl` file onto the page. Press `?` for the keyboard shortcuts.

Change the UI credentials with the `SLRAG_UI_USERNAME` / `SLRAG_UI_PASSWORD` environment variables. Only `/ui/*` and `/api/*` are password-protected; `/ws/*` and `/health` are not.

## Voice input

Voice input requires **Chrome or Edge**. Click **🎤 Voice** in the top bar (or press `M`) and ask a question. The transcript streams into the pipeline as you speak. After 2.5 s of silence the utterance ends and the answer is drafted.

The browser's speech service (Google or Microsoft) transcribes the audio; the server only receives text. It works on `localhost` or over HTTPS.

## Switch to a real LLM

The default `llm.backend: heuristic` is a deterministic stand-in drafter, so no model server is needed and results are reproducible. To draft with a real model:

1. Set `llm.backend: ollama` in `config.yaml`.
2. Run `make model`.
3. Restart with `make up`.

Inside Docker Compose, the app reaches Ollama at `http://ollama:11434` (`SLRAG_OLLAMA_URL`). Locally, it uses `llm.ollama_url`. If Ollama is unreachable, each call falls back to the heuristic path and the turn still completes.

Note that `config.yaml` is frozen (`frozen: true`) and `tests/test_config_freeze.py` pins its hash. Changing the backend makes that test fail, by design: the published numbers were measured with the heuristic backend.

## Run experiments

```bash
python -m slrag.cli replay eval/scenarios --split test --out out/ours_test.jsonl
python scripts/run_experiments.py
python scripts/compliance_audit.py
```

| Command | Writes | Contents |
|---|---|---|
| `slrag.cli replay` (`make replay`) | `out/summary.json`, `out/report.md` | metrics and gates, Ours vs B1 vs B0 |
| `run_experiments.py` (`make experiments`) | `out/final_experiments.json` | ablations A1–A5; also served to the UI's Metrics tab |
| `compliance_audit.py` (`make audit`) | `out/compliance.json` | the six compliance checks |

The test split is the evaluation split. Thresholds are calibrated on the tune split (`scripts/calibrate.py --split tune`) and frozen before the test run.

## Run tests

```bash
make test        # or: pytest tests/ -q
```

## Results (test split, frozen config `cfg_hash 90e68e6053d494aa`)

| Gate | Condition | Measured | |
|---|---|---|---|
| G1 recall improvement | recall@10 Ours ≥ B1 | 0.926 vs 0.846 | ✅ |
| G2 early retrieval | early-retrieval rate ≥ 0.80 | 0.950 | ✅ |
| G3 groundedness preservation | groundedness Ours ≥ B1 | 0.975 vs 0.956 | ✅ |
| G4 grounding | groundedness ≥ 0.85, hallucinated-ID rate = 0 | 0.975, 0.000 | ✅ |
| G5 late-detail refinement | preservation = 1.0, no restarts, full lineage | 1.000, 0, 1.000 | ✅ |
| G6 trace coverage | coverage = 1.0 | 1.000 | ✅ |

Latency is virtual replay time and cost is notional.

The dense retriever is a hashed n-gram placeholder, not a neural embedding model; the ablations show BM25 alone retrieves better. The benchmark report covers this and the other limits.

## Documentation

- [docs/architecture_brief.md](docs/architecture_brief.md): architecture, data flow, trigger logic, grounding, trade-offs, deployment, limitations
- [docs/benchmark_report.md](docs/benchmark_report.md): full metric table, gates G1–G6, ablations A1–A5, failure analysis
- [data/CORPUS_README.md](data/CORPUS_README.md): the synthetic Nexora corpus

## Layout

```
slrag/          engine: gateway, control (T0/T1/T2), plan, retrieval, pipeline, answer, state, server, ui
config.yaml     the single source of every threshold (frozen)
data/           corpus JSON + prebuilt index
eval/scenarios/ tune / test scenario splits (evaluation only; not in the Docker image)
scripts/        calibrate, run_experiments, compliance_audit, validate_scenarios
tests/          pytest suite
docs/           architecture brief, benchmark report
```
