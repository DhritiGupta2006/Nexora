# PHASE 4: Cascade Controller Integration Guide

## Overview

Phase 4 implements the **streaming control layer** for RAG systems. It provides:

1. **Three-tier cascade controller** (T0 → T1 → T2)
2. **Evidence cache** with similarity-based reuse rules
3. **Streaming turn state machine** (WAIT → PROVISIONAL → COMMIT → UTTERANCE_END)
4. **Presenter component** for answer suppression and reuse
5. **Early retrieval** at COMMIT epoch (before utterance_end)
6. **Controller decision events** with latency telemetry

---

## Architecture

### Three-Tier Decision Cascade

```
┌─────────────────────────────────────────────────────────────┐
│  Current Utterance + Previous Context                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │   T0: Rule-Based       │ ← ~1-2ms
            │   - Exact repetition   │
            │   - Fuzzy match        │
            │   - Generic query      │
            │   - Follow-up context  │
            └────────┬───────────────┘
                     │
         SUPPRESS ◄──┼──► RETRIEVE ──► Cache Check
         (0% retrieval) │              │
                        │              ▼
                        │         ┌──────────────┐
                        │         │  Cache Hit?  │
                        │         │  cos ≥ 0.82  │
                        │         └──┬───────┬───┘
                        │            │       │
                        │         YES│       │NO
                        │            │       ▼
                        │            │  ┌────────────────┐
                        │            │  │  T1: Drift     │ ← ~5-8ms
                        │            │  │  - Cosine sim  │
                        │            │  │  - Similarity  │
                        │            │  └────┬────┬──────┘
                        │            │       │    │
                        │       ┌─────┘       │    └────────┐
                        │       │             │             │
                        │   SUPPRESS    RETRIEVE    ESCALATE
                        │       │             │             │
                        └───────┼─────────────┼─────────────┼──────┐
                                │             │             │      │
                                │             │    ┌────────▼──────┘
                                │             │    │
                                │             │    ▼
                                │             │  ┌─────────────────┐
                                │             │  │  T2: LLM Gating │ ← ~50-100ms
                                │             │  │  - Confidence   │
                                │             │  │  - Async gating │
                                │             │  └────┬────────┬──┘
                                │             │       │        │
                                │             │   SUPPRESS  RETRIEVE
                                │             │       │        │
                                └─────────────┴───────┴────────┘
                                              │
                                              ▼
                                      ┌──────────────────┐
                                      │   Controller     │
                                      │   Decision Event │
                                      │  (tier, latency) │
                                      └──────────────────┘
```

### Streaming Turn State Machine

```
┌─────────────────────────────────────────────────────────────────┐
│  Turn Lifecycle                                                 │
└─────────────────────────────────────────────────────────────────┘

 WAIT          PROVISIONAL        COMMIT          UTTERANCE_END
  │                 │                │                  │
  │ [utterance   │  [accumulate  │ [early         │ [present
  │  starts]     │   first N     │ retrieval]     │  final
  │              │   chunks]     │ [caching]      │  answer]
  │              │               │                │
  ├─────────────►├──────────────►├───────────────►├────────►
  │              │               │                │
  │              │               ▼                │
  │              │          Retrieval             │
  │              │          Logic Runs            │
  │              │          (T0+T1)               │
  │              │          ~10ms                 │
  │              │                                │
  │              └────────────────────────────────┘
  │                                               │
  └──────────────────────────────────────────────►
                                                  │
                                       Cleanup & emit metrics

Legend:
  - WAIT: Turn initialized, awaiting chunks
  - PROVISIONAL: Buffering initial chunks
  - COMMIT: Control decision made, early retrieval starts
  - UTTERANCE_END: Turn complete, answer finalized
```

---

## Core Components

### 1. T0: Rule-Based Tier (Fastest Path)

**Decision Time:** ~1-2ms

**Rules:**
- **Exact Repetition:** Text match (case-insensitive)
- **Fuzzy Repetition:** Levenshtein distance > 0.85
- **Generic Queries:** Pattern matching ("what", "who", "explain", etc.)
- **Follow-up Context:** Detected by conjunctions ("and", "also", "furthermore")

**Output:**
```typescript
{
  decision: 'SUPPRESS' | 'RETRIEVE' | 'CONTINUE',
  reason: string,           // e.g., 'EXACT_REPETITION'
  confidence: number        // 0.5-1.0
}
```

**When Triggered:**
- Suppress path (confidence ~0.95): Skip retrieval, reuse prior answer
- Continue path (confidence ~0.5-0.8): Escalate to T1

---

### 2. T1: Drift-Based Tier (Cache Layer)

**Decision Time:** ~5-8ms

**Mechanism:**
```javascript
similarity = cosine_similarity(current_embedding, previous_embedding)
drift_score = 1 - similarity

if (similarity >= 0.82) {
  // Suppress: context hasn't drifted
  decision = 'SUPPRESS'
  confidence = 0.9
}

if (drift_score >= 0.5) {
  // Escalate to T2 for LLM gating
  decision = 'ESCALATE'
  confidence = 0.6
}

// Check cache for similarity hits
if (cache.get(current_embedding, cos >= 0.82)) {
  decision = 'CACHE_HIT'
  confidence = 0.95
}
```

**Cache Reuse Rules:**
- Hit if: `cosine_similarity(query, cached_query) ≥ 0.82`
- No slot conflicts (one cached item per utterance slot)
- Evict oldest on slot exhaustion (limit: 10 slots)

**Output:**
```typescript
{
  decision: 'SUPPRESS' | 'RETRIEVE' | 'ESCALATE' | 'CACHE_HIT',
  driftScore: number,       // 0.0-1.0
  reason: string,           // e.g., 'SIMILAR_CONTEXT'
  confidence: number        // 0.75-0.95
}
```

---

### 3. T2: LLM-Based Gating Tier (High Confidence)

**Decision Time:** ~50-100ms (async)

**Triggered only if:**
- T1 escalation (high drift, 0.5-1.0)
- AND previous context exists
- AND not already suppressed

**LLM Prompt Pattern:**
```
Given:
  Previous Question: "{previous_utterance}"
  Current Question: "{current_utterance}"
  Context Window: {context}

Determine if new retrieval is needed for current question.
Respond ONLY with: RETRIEVE or SUPPRESS
Confidence: [0.7-1.0]
```

**Output:**
```typescript
{
  decision: 'SUPPRESS' | 'RETRIEVE',
  confidence: number,       // 0.7-1.0
  reasoning: string
}
```

---

### 4. Evidence Cache

**Design:**
- Key: `embedding` (vectorized query)
- Value: `CachedEvidence` (sources + metadata)
- Limit: 10 slots (LRU eviction)

**Cache Hit Conditions:**
```javascript
// Exact slot hit
if (cache.slots[utteranceId]) {
  return cache.get(utteranceId)
}

// Similarity hit across cache
for (cached of cache.values()) {
  similarity = cosine_similarity(current_embedding, cached.embedding)
  if (similarity >= 0.82 && no_slot_conflict) {
    return cached
  }
}
```

**Redundancy Reduction Metric:**
```
reduction = (cache_hits / total_queries) * 100%
Goal: ≥30% on repeat-heavy scenarios
```

Example:
- 10 queries, 3 unique topics
- Query sequence: Q1, Q1_variant, Q2, Q1_variant2, Q2_variant, Q3, Q3, Q1, Q3_variant, Q2
- Cache hits: 6/10 = 60% redundancy reduction

---

### 5. Streaming Turn State Machine

**Initialization:**
```typescript
const state = controller.initializeTurn(utteranceId)
// state.currentEpoch = 'WAIT'
// state.chunkBuffer = []
// state.early_retrieval_started = false
```

**Epoch Transitions:**

| Epoch | Duration | Role | Early Retrieval |
|-------|----------|------|-----------------|
| WAIT | 0-100ms | Awaiting chunks | - |
| PROVISIONAL | 100-300ms | Buffer first N chunks | - |
| COMMIT | ~300-400ms | Control decision made | ✓ START HERE |
| UTTERANCE_END | Variable | Answer finalized | - |

**Transitions:**
```typescript
controller.transitionEpoch(utteranceId, 'WAIT')
controller.transitionEpoch(utteranceId, 'PROVISIONAL')
controller.transitionEpoch(utteranceId, 'COMMIT')  // ← Early retrieval starts
controller.transitionEpoch(utteranceId, 'UTTERANCE_END')
```

---

### 6. Presenter Component

**Role:** Byte-for-byte answer reuse

**Methods:**
```typescript
// Cache answer after completion
presenter.cacheAnswer(utteranceId, answer_text)

// Retrieve prior answer for suppression
presenter.getPriorAnswer(priorUtteranceId)

// Reuse with no modifications
presenter.reusePriorAnswer(currentId, priorId)
```

**Constraints:**
- Preserve exact byte encoding
- No normalization or transformation
- Metadata preserved (citations, confidence scores)

---

### 7. Controller Decision Events

**Emitted for every decision:**
```typescript
controller.on('controller:decision', (decision) => {
  console.log({
    tier: 'T0' | 'T1' | 'T2',
    decision: 'SUPPRESS' | 'RETRIEVE' | 'CACHE_HIT',
    driftScore: 0.0-1.0,      // Only for T1
    confidence: 0.5-1.0,
    reason: string,           // Rule or path taken
    suppressedAnswerId?: string,
    cacheHitId?: string,
    timestamp: number,
    latencyMs: number         // ≤10ms for T0+T1
  })
})
```

**Event Lifecycle:**
```
turn:initialized
  ↓
epoch:transition (WAIT → PROVISIONAL)
  ↓
epoch:transition (PROVISIONAL → COMMIT)
  ↓
retrieval:early_start
  ↓
controller:decision (T0/T1/T2)
  ↓
[Optional] evidence:cached
  ↓
epoch:transition (COMMIT → UTTERANCE_END)
  ↓
turn:complete
```

---

## Integration Example

### With Streaming Response Pipeline

```typescript
import { CascadeController } from './phase4_cascade_controller'

const controller = new CascadeController()

// 1. Initialize turn
const turnId = generateId()
controller.initializeTurn(turnId)

// 2. Wait for user utterance completion
onUtteranceComplete(async (utterance) => {
  // Record utterance
  controller.recordUtterance(utterance)
  
  // 3. Transition through epochs
  controller.transitionEpoch(turnId, 'PROVISIONAL')
  
  // Buffer first N chunks
  for await (const chunk of incomingStream) {
    controller.addChunk(turnId, chunk)
    if (controller.getTurnState(turnId)!.chunkIndex >= MIN_CHUNKS) {
      break
    }
  }
  
  // 4. Move to COMMIT → triggers early retrieval
  controller.transitionEpoch(turnId, 'COMMIT')
  
  // 5. Get control decision
  const decision = await controller.decideRetrieval(
    utterance,
    previousUtterance
  )
  
  // 6. Branch based on decision
  if (decision.decision === 'SUPPRESS') {
    // Reuse prior answer
    const answer = controller.suppressAndReuse(turnId, previousUtteranceId)
    emitAnswer(answer)
    
  } else if (decision.decision === 'CACHE_HIT') {
    // Retrieve from cache
    const cachedEvidence = cache.get(decision.cacheHitId)
    emitAnswer(generateAnswer(cachedEvidence))
    
  } else {
    // Full retrieval pipeline
    const evidence = await retriever.retrieve(utterance.text)
    controller.storeRetrievedEvidence(turnId, evidence)
    const answer = await generator.generate(utterance.text, evidence)
    emitAnswer(answer)
  }
  
  // 7. Complete turn
  controller.transitionEpoch(turnId, 'UTTERANCE_END')
  controller.completeTurn(turnId, finalAnswer)
})
```

---

## Performance Metrics

### Latency Targets

| Tier | Decision | Max Latency | Typical |
|------|----------|-------------|---------|
| T0 | Rule-based | ~2ms | 0.5-1.5ms |
| T1 | Drift + Cache | ~8ms | 3-7ms |
| T0+T1 Combined | **≤10ms** | 5-8ms |
| T2 | LLM gating | ~100ms | 50-150ms |

**Constraint:** T0+T1 latency ≤10ms per chunk

### Cache Effectiveness

Target: **≥30% redundancy reduction** on repeat-heavy scenarios

**Scenarios:**
1. **High Repetition** (3 unique queries, 10 requests)
   - Expected hits: 7/10 = 70% reduction
   
2. **Moderate Drift** (5 unique, 10 requests)
   - Expected hits: 4/10 = 40% reduction
   
3. **High Drift** (8+ unique, 10 requests)
   - Expected hits: 1-2/10 = 10-20% reduction (acceptable)

### Retrieval Reduction

- **T0 Suppression:** 0% retrieval on exact/fuzzy repeats
- **T1 Cache Hit:** 0% retrieval on similarity ≥0.82
- **Overall:** 30-70% reduction depending on query distribution

---

## Testing Acceptance Criteria

✓ **3-Turn Scenario:**
- Turn 1: Initial query → RETRIEVE
- Turn 2: Exact repeat → T0 SUPPRESS (0% retrieval)
- Turn 3: Similar query → Cache hit (0% retrieval)
- Latency: All decisions ≤10ms

✓ **Suppression Preserves Answer:**
- Byte-for-byte reuse
- No normalization
- Metadata preserved

✓ **Cache Reuse ≥30%:**
- 10-query repeat-heavy test
- ≥3 cache hits expected

✓ **Latency ≤10ms:**
- T0+T1 combined: ≤10ms
- P95: ≤8ms
- P100: ≤12ms (acceptable variance)

---

## Implementation Checklist

- [x] T0 tier with rules
- [x] T1 tier with cosine similarity
- [x] T2 tier with LLM gating skeleton
- [x] Evidence cache with slot management
- [x] Cache reuse rules (cos ≥ 0.82)
- [x] Streaming state machine (4 epochs)
- [x] Early retrieval trigger at COMMIT
- [x] Presenter for suppression path
- [x] Controller decision events
- [x] Latency tracking per decision
- [x] Event emitters for all state changes
- [x] Comprehensive test suite

---

## Next Phases (Context)

**Phase 5:** Answer Generation with Cache Awareness
- Generate from cached evidence
- Update cache with new evidence sources
- Merge multi-source evidence

**Phase 6:** Streaming Output & Final Integration
- Chunk-by-chunk streaming
- Progressive rendering
- Latency per chunk monitoring

---

## References

- **Streaming RAG:** Earlier phases establish retriever and generator
- **Cosine Similarity:** Distance metric for embedding comparison
- **LRU Cache:** Eviction strategy for evidence slots
- **State Machine:** Turn lifecycle and epoch tracking
