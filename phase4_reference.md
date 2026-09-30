# PHASE 4: Quick Reference Card

## What is Phase 4?

**Cascade Controller** - The streaming control layer that decides when to retrieve, suppress, or cache for RAG systems.

```
Input:  Current Utterance + Previous Context
Output: ControllerDecision (tier, decision, latency)
Goal:   Reduce redundant retrieval by ≥30% with ≤10ms latency
```

---

## Three-Tier Decision Cascade

### Tier 0: Rules (~1-2ms)
```
Rule-Based Decisions
├─ Exact Repetition    → SUPPRESS
├─ Fuzzy Match (>85%)  → SUPPRESS
├─ Generic Query       → RETRIEVE
└─ Follow-up Context   → CONTINUE
```

### Tier 1: Drift (~5-8ms)
```
Embedding-Based Decisions
├─ Similarity ≥ 0.82       → SUPPRESS / CACHE_HIT
├─ Drift Score 0.5-1.0     → ESCALATE to T2
└─ No Previous Context     → RETRIEVE
```

### Tier 2: LLM-Gating (~50-100ms, async)
```
LLM-Based Decisions (triggered only if escalated)
├─ High Confidence         → SUPPRESS or RETRIEVE
└─ Handles edge cases
```

---

## Key Components

| Component | Purpose | Method |
|-----------|---------|--------|
| **T0RuleBasedTier** | Fast rule decisions | `decide(current, previous)` |
| **T1DriftTier** | Embedding similarity | `decide(embedding, prev_emb)` |
| **T2LLMGatingTier** | LLM confidence checks | `async decide(utterances)` |
| **EvidenceCache** | Caches retrieved sources | `get(), put()` |
| **Presenter** | Answer reuse/suppression | `reusePriorAnswer()` |
| **CascadeController** | Main orchestrator | `decideRetrieval()` |

---

## State Machine: Turn Lifecycle

```
WAIT (0ms)
  ↓
PROVISIONAL (100-300ms)     [buffer chunks]
  ↓
COMMIT (~300-400ms)         [early retrieval starts here]
  ↓
UTTERANCE_END               [answer finalized]
```

**Transition Methods:**
```typescript
controller.initializeTurn(utteranceId)
controller.transitionEpoch(utteranceId, 'WAIT' | 'PROVISIONAL' | 'COMMIT' | 'UTTERANCE_END')
controller.addChunk(utteranceId, chunk)
controller.startEarlyRetrieval(utteranceId, utterance)
controller.completeTurn(utteranceId, answer)
```

---

## Control Flow

### Decision Cascade
```typescript
const decision = await controller.decideRetrieval(current, previous)

// Checks in order:
// 1. T0: Exact repetition?     → SUPPRESS (done)
// 2. T1: Cache hit?            → CACHE_HIT (done)
// 3. T1: High similarity?      → SUPPRESS (done)
// 4. T1: High drift?           → ESCALATE
// 5. T2: LLM gating (if escalated)
// 6. Default: RETRIEVE
```

### Suppression Path (T0)
```typescript
if (decision.decision === 'SUPPRESS') {
  const answer = controller.suppressAndReuse(
    currentUtteranceId,
    previousUtteranceId
  )
  // → Returns prior answer byte-for-byte, no retrieval
}
```

### Cache Hit Path (T1)
```typescript
if (decision.decision === 'CACHE_HIT') {
  const cachedEvidence = cache.get(decision.cacheHitId)
  // → Reuse cached evidence, generate from cache
}
```

### Retrieval Path
```typescript
if (decision.decision === 'RETRIEVE') {
  const evidence = await retriever.retrieve(utterance.text)
  controller.storeRetrievedEvidence(utteranceId, evidence)
  // → Full retrieval pipeline
}
```

---

## Event Emissions

```typescript
// Listen to decisions
controller.on('controller:decision', (decision) => {
  console.log(`[${decision.tier}] ${decision.decision}`)
  console.log(`Latency: ${decision.latencyMs}ms`)
})

// Full event lifecycle
controller.on('turn:initialized', ...)
controller.on('epoch:transition', ...)
controller.on('retrieval:early_start', ...)
controller.on('controller:decision', ...)
controller.on('evidence:cached', ...)
controller.on('suppression:answer_reused', ...)
controller.on('turn:complete', ...)
```

---

## Cache Mechanics

### Cache Hit Rule
```
HIT if:
  ├─ Direct slot match (exact utterance ID) OR
  └─ Similarity match (cos ≥ 0.82) AND no slot conflict
```

### Eviction (LRU)
```
Limit: 10 slots
When full: evict oldest cached item
Time field: automatically tracked
```

### Metrics
```typescript
const stats = controller.getCacheStats()
// {
//   size: 5,              // items cached
//   slots: 4,             // active slots used
//   totalReuses: 8        // total cache hits
// }

const reduction = (cacheHits / totalQueries) * 100
// Goal: ≥30%
```

---

## Latency Targets

| Component | Target | Typical |
|-----------|--------|---------|
| T0 alone | <2ms | 0.5-1.5ms |
| T1 alone | <8ms | 3-7ms |
| **T0+T1 combined** | **≤10ms** | 5-8ms |
| T2 (async) | ~100ms | 50-150ms |

**Critical:** T0+T1 must complete in ≤10ms

---

## Usage Example

```typescript
import { CascadeController } from './phase4_cascade_controller'

const controller = new CascadeController()

// 1. Initialize turn
const turnId = 'turn_123'
controller.initializeTurn(turnId)

// 2. Record utterance
const utterance = {
  id: turnId,
  text: 'What is machine learning?',
  embedding: [0.1, 0.2, ...],  // 256-dim vector
  timestamp: Date.now()
}
controller.recordUtterance(utterance)

// 3. Make control decision
const prev = previousUtterance // if exists
const decision = await controller.decideRetrieval(utterance, prev)

// 4. Branch based on decision
switch (decision.decision) {
  case 'SUPPRESS':
    const answer = controller.suppressAndReuse(turnId, prev.id)
    emit(answer)
    break
    
  case 'CACHE_HIT':
    const cached = cache.get(decision.cacheHitId)
    emit(generateAnswer(cached))
    break
    
  case 'RETRIEVE':
    const evidence = await retriever.retrieve(utterance.text)
    controller.storeRetrievedEvidence(turnId, evidence)
    emit(generateAnswer(evidence))
    break
}

// 5. Complete turn
controller.completeTurn(turnId, finalAnswer)
```

---

## Testing

### Run Tests
```bash
npx ts-node phase4_tests.ts
```

### Run Example
```bash
npx ts-node phase4_example.ts
```

### Test Coverage

| Test | Validates |
|------|-----------|
| `test_3TurnScenario` | Accept criteria (T0 suppress, T1 cache, latency) |
| `test_StreamingStateMachine` | Epoch transitions, early retrieval flag |
| `test_CacheReuse` | ≥30% redundancy reduction |
| `test_FuzzyRepetition` | T0 fuzzy matching |
| `test_LatencyConstraints` | ≤10ms on 100 iterations |

---

## Acceptance Criteria (✓ MUST PASS)

```
✓ Turn 2 (repeat) → T0 SUPPRESS
  └─ Zero retrieval, reuse prior answer

✓ Turn 3 (similar) → T1 CACHE_HIT
  └─ Zero retrieval, reuse cached evidence

✓ All decisions ≤ 10ms
  └─ P95: ≤8ms, P100: ≤12ms (tolerance)

✓ ≥30% redundancy reduction
  └─ Fewer retrievals on repeat-heavy queries
```

---

## Common Patterns

### Pattern 1: Exact Repeat Detection
```typescript
// Turn 2 repeats Turn 1 exactly
// → T0 rule detects it
// → SUPPRESS decision
// → No retrieval, reuse answer
```

### Pattern 2: Fuzzy Repeat
```typescript
// "What is ML?" → "What is machine learning?"
// → T0 fuzzy match (>85% similarity)
// → SUPPRESS decision
```

### Pattern 3: Drift Detection
```typescript
// Turn N embedding significantly differs from Turn N-1
// → T1 drift score > 0.5
// → ESCALATE to T2
// → LLM gating decides
```

### Pattern 4: Cache Chain
```typescript
// Query A → retrieved (full pipeline)
// Query B (similar to A) → cache hit
// Query C (similar to B) → cache hit again
// Result: 66% reduction on 3 queries
```

---

## Troubleshooting

### Latency > 10ms?
- Check T0 rule complexity (Levenshtein distance calculation can be slow)
- Optimize cosine similarity computation
- Use vectorized operations if possible

### Cache hit rate low?
- Embedding quality check: ensure consistent normalization
- Threshold review: maybe 0.82 is too high?
- Check for embedding drift over time

### Suppressions not working?
- Verify exact repetition logic: case sensitivity, whitespace
- Test fuzzy match threshold (currently 0.85)
- Check if previous utterance is properly stored

### Memory usage?
- Cache limit: 10 slots (adjustable)
- Turn state cleanup: happens 100ms after completion
- Large embeddings: consider dimension reduction

---

## Next Steps (Phase 5)

**Answer Generation with Cache Awareness**
- Generate from cached evidence
- Multi-source merging
- Citation tracking

---

## Files in This Phase

| File | Purpose |
|------|---------|
| `phase4_cascade_controller.ts` | Main implementation |
| `phase4_tests.ts` | Test suite (5 tests) |
| `phase4_example.ts` | Runnable 3-turn scenario |
| `phase4_integration.md` | Integration guide |
| `phase4_reference.md` | This file |

---

## Key Metrics to Monitor

```typescript
// Per decision
decision.latencyMs              // ≤10ms for T0+T1
decision.tier                   // T0 | T1 | T2
decision.driftScore             // 0.0-1.0 (T1 only)
decision.confidence             // 0.5-1.0

// Per turn
state.chunkIndex                // chunks buffered
state.early_retrieval_started   // boolean at COMMIT

// Cache
stats.size                       // items cached
stats.totalReuses                // total cache hits
redundancyReduction              // % (target ≥30%)
```

---

## Advanced Configuration

```typescript
// Tune thresholds
const SIMILARITY_THRESHOLD = 0.82    // Cache hit threshold
const DRIFT_CRITICAL = 0.5            // Escalate to T2
const CACHE_SLOT_LIMIT = 10          // Max cached items
const LEVENSHTEIN_THRESHOLD = 0.85   // Fuzzy match

// Customize T0 rules
t0.addRule('custom_rule', (utterance) => {
  // Custom logic
  return { decision: 'SUPPRESS', confidence: 0.9 }
})

// Custom LLM prompt for T2
t2.setPromptTemplate(`
  Question 1: {prev_q}
  Question 2: {curr_q}
  Needs new retrieval? YES or NO
`)
```

---

## References

**Key Concepts:**
- Cosine Similarity: measure embedding distance
- LRU Cache: least-recently-used eviction
- State Machine: turn lifecycle management
- Drift Score: embedding change magnitude

**Literature:**
- "Retrieval-Augmented Generation" (RAG) foundations
- "Dense Passage Retrieval" (embeddings)
- "Early Termination Strategies" (streaming systems)

---

**Last Updated:** Phase 4 Implementation
**Version:** 1.0
**Status:** Ready for Integration
