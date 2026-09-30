/**
 * PHASE 4: Cascade Controller, Early Retrieval & Evidence Cache
 * 
 * Three-tier streaming control layer for RAG:
 * - T0: Rule-based decisions (repetition, presentation, no-anchor suppression) - ~1ms
 * - T1: Drift-based scoring (cosine similarity threshold 0.82) - ~5ms
 * - T2: LLM-based gating with confidence scores - ~50-100ms (async)
 * 
 * Features:
 * - Evidence cache with cosine similarity reuse rules
 * - Streaming turn state machine (WAIT → PROVISIONAL → COMMIT → utterance_end)
 * - Presenter component for byte-for-byte answer suppression
 * - Early retrieval at COMMIT epoch (before utterance_end)
 * - Controller decision events with telemetry
 */

import { EventEmitter } from 'events';

// ============================================================================
// Types & Interfaces
// ============================================================================

export interface Utterance {
  id: string;
  text: string;
  embedding?: number[];
  timestamp: number;
  speaker?: string;
}

export interface CachedEvidence {
  id: string;
  utteranceId: string;
  content: string;
  sources: Source[];
  embedding?: number[];
  timestamp: number;
  retrievedAt: number;
  reusedCount: number;
}

export interface Source {
  id: string;
  title: string;
  snippet: string;
  confidence: number;
}

export interface ControllerDecision {
  tier: 'T0' | 'T1' | 'T2';
  decision: 'SUPPRESS' | 'RETRIEVE' | 'CACHE_HIT';
  driftScore: number;
  confidence: number;
  reason: string;
  cacheHitId?: string;
  suppressedAnswerId?: string;
  timestamp: number;
  latencyMs: number;
}

export interface StreamingEpoch {
  epoch: 'WAIT' | 'PROVISIONAL' | 'COMMIT' | 'UTTERANCE_END';
  utteranceId: string;
  chunkIndex: number;
  timestamp: number;
}

export interface StreamingTurnState {
  utteranceId: string;
  currentEpoch: StreamingEpoch['epoch'];
  chunkBuffer: string[];
  chunkIndex: number;
  controller_decision?: ControllerDecision;
  retrieved_evidence?: CachedEvidence;
  early_retrieval_started: boolean;
  presented_answer?: string;
  started_at: number;
}

// ============================================================================
// Evidence Cache
// ============================================================================

class EvidenceCache {
  private cache: Map<string, CachedEvidence> = new Map();
  private slots: Map<string, string> = new Map(); // utteranceId -> cacheId
  private readonly SLOT_LIMIT = 10;
  private readonly SIMILARITY_THRESHOLD = 0.82;

  get(utteranceId: string, embedding: number[]): CachedEvidence | null {
    // Check direct slot hit
    const cachedId = this.slots.get(utteranceId);
    if (cachedId) {
      const cached = this.cache.get(cachedId);
      if (cached) {
        cached.reusedCount++;
        return cached;
      }
    }

    // Check similarity-based hits across all cached evidence
    for (const cached of this.cache.values()) {
      if (!cached.embedding) continue;

      const similarity = this.cosineSimilarity(embedding, cached.embedding);
      if (similarity >= this.SIMILARITY_THRESHOLD) {
        // Check slot conflict
        const existingSlot = this.slots.get(utteranceId);
        if (!existingSlot || existingSlot === cached.id) {
          cached.reusedCount++;
          this.slots.set(utteranceId, cached.id);
          return cached;
        }
      }
    }

    return null;
  }

  put(evidence: CachedEvidence): void {
    // Evict oldest if at limit
    if (this.cache.size >= this.SLOT_LIMIT) {
      let oldest = Array.from(this.cache.values()).sort(
        (a, b) => a.timestamp - b.timestamp
      )[0];
      this.cache.delete(oldest.id);
      // Remove slot mappings for evicted evidence
      for (const [uId, cId] of this.slots.entries()) {
        if (cId === oldest.id) {
          this.slots.delete(uId);
        }
      }
    }

    this.cache.set(evidence.id, evidence);
    this.slots.set(evidence.utteranceId, evidence.id);
  }

  stats(): {
    size: number;
    slots: number;
    totalReuses: number;
  } {
    const totalReuses = Array.from(this.cache.values()).reduce(
      (sum, e) => sum + e.reusedCount,
      0
    );
    return {
      size: this.cache.size,
      slots: this.slots.size,
      totalReuses,
    };
  }

  private cosineSimilarity(a: number[], b: number[]): number {
    if (a.length !== b.length) return 0;
    let dotProduct = 0;
    let normA = 0;
    let normB = 0;

    for (let i = 0; i < a.length; i++) {
      dotProduct += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }

    const denominator = Math.sqrt(normA) * Math.sqrt(normB);
    if (denominator === 0) return 0;

    return dotProduct / denominator;
  }
}

// ============================================================================
// T0: Rule-Based Decision Tier
// ============================================================================

interface T0Decision {
  decision: 'SUPPRESS' | 'RETRIEVE' | 'CONTINUE';
  reason: string;
  confidence: number;
}

class T0RuleBasedTier {
  private utteranceHistory: Map<string, Utterance> = new Map();
  private answerHistory: Map<string, string> = new Map();

  decide(
    currentUtterance: Utterance,
    previousUtterance?: Utterance
  ): T0Decision {
    const startTime = performance.now();

    // Rule 1: Exact repetition suppression
    if (previousUtterance && this.isExactRepetition(currentUtterance.text, previousUtterance.text)) {
      return {
        decision: 'SUPPRESS',
        reason: 'EXACT_REPETITION',
        confidence: 1.0,
      };
    }

    // Rule 2: Near-repetition detection (fuzzy match)
    if (previousUtterance && this.isFuzzyRepetition(currentUtterance.text, previousUtterance.text)) {
      return {
        decision: 'SUPPRESS',
        reason: 'FUZZY_REPETITION',
        confidence: 0.95,
      };
    }

    // Rule 3: Presentation-only (no anchors, generic queries)
    if (this.isGenericQuery(currentUtterance.text)) {
      return {
        decision: 'RETRIEVE',
        reason: 'GENERIC_PRESENTATION_QUERY',
        confidence: 0.85,
      };
    }

    // Rule 4: No-anchor suppression (follow-up context)
    if (this.hasFollowUpContext(currentUtterance.text)) {
      return {
        decision: 'CONTINUE',
        reason: 'FOLLOW_UP_CONTEXT',
        confidence: 0.8,
      };
    }

    return {
      decision: 'CONTINUE',
      reason: 'DEFAULT_CONTINUE',
      confidence: 0.5,
    };
  }

  recordUtterance(utterance: Utterance): void {
    this.utteranceHistory.set(utterance.id, utterance);
  }

  recordAnswer(utteranceId: string, answer: string): void {
    this.answerHistory.set(utteranceId, answer);
  }

  getLastAnswer(utteranceId: string): string | undefined {
    return this.answerHistory.get(utteranceId);
  }

  private isExactRepetition(current: string, previous: string): boolean {
    return current.toLowerCase().trim() === previous.toLowerCase().trim();
  }

  private isFuzzyRepetition(current: string, previous: string): boolean {
    const normalize = (s: string) => s.toLowerCase().trim().replace(/[?!.]+$/, '');
    const currNorm = normalize(current);
    const prevNorm = normalize(previous);

    const distance = this.levenshteinDistance(currNorm, prevNorm);
    const maxLen = Math.max(currNorm.length, prevNorm.length);
    const similarity = 1 - distance / maxLen;

    return similarity > 0.85;
  }

  private isGenericQuery(text: string): boolean {
    const genericPatterns = /^(what|who|where|when|why|how|tell me|explain|describe)\b/i;
    return genericPatterns.test(text);
  }

  private hasFollowUpContext(text: string): boolean {
    const followUpPatterns = /^(and|also|furthermore|moreover|besides|what about|how about)/i;
    return followUpPatterns.test(text);
  }

  private levenshteinDistance(a: string, b: string): number {
    const matrix: number[][] = [];

    for (let i = 0; i <= b.length; i++) {
      matrix[i] = [i];
    }
    for (let j = 0; j <= a.length; j++) {
      matrix[0][j] = j;
    }

    for (let i = 1; i <= b.length; i++) {
      for (let j = 1; j <= a.length; j++) {
        if (b.charAt(i - 1) === a.charAt(j - 1)) {
          matrix[i][j] = matrix[i - 1][j - 1];
        } else {
          matrix[i][j] = Math.min(
            matrix[i - 1][j - 1] + 1,
            matrix[i][j - 1] + 1,
            matrix[i - 1][j] + 1
          );
        }
      }
    }

    return matrix[b.length][a.length];
  }
}

// ============================================================================
// T1: Drift-Based Scoring Tier
// ============================================================================

interface T1Decision {
  decision: 'SUPPRESS' | 'RETRIEVE' | 'ESCALATE';
  driftScore: number;
  reason: string;
  confidence: number;
}

class T1DriftTier {
  private readonly SIMILARITY_THRESHOLD = 0.82;
  private readonly DRIFT_CRITICAL = 0.5;

  decide(
    currentEmbedding: number[],
    previousEmbedding?: number[]
  ): T1Decision {
    if (!previousEmbedding) {
      return {
        decision: 'RETRIEVE',
        driftScore: 0,
        reason: 'NO_PREVIOUS_EMBEDDING',
        confidence: 0.7,
      };
    }

    const similarity = this.cosineSimilarity(currentEmbedding, previousEmbedding);
    const driftScore = 1 - similarity; // Higher drift = more different

    if (similarity >= this.SIMILARITY_THRESHOLD) {
      return {
        decision: 'SUPPRESS',
        driftScore,
        reason: 'SIMILAR_CONTEXT',
        confidence: 0.9,
      };
    }

    if (driftScore >= this.DRIFT_CRITICAL) {
      return {
        decision: 'ESCALATE',
        driftScore,
        reason: 'HIGH_DRIFT_NEEDS_LLM',
        confidence: 0.6,
      };
    }

    return {
      decision: 'RETRIEVE',
      driftScore,
      reason: 'MODERATE_DRIFT',
      confidence: 0.75,
    };
  }

  private cosineSimilarity(a: number[], b: number[]): number {
    if (a.length !== b.length) return 0;

    let dotProduct = 0;
    let normA = 0;
    let normB = 0;

    for (let i = 0; i < a.length; i++) {
      dotProduct += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }

    const denominator = Math.sqrt(normA) * Math.sqrt(normB);
    if (denominator === 0) return 0;

    return dotProduct / denominator;
  }
}

// ============================================================================
// T2: LLM-Based Gating Tier
// ============================================================================

interface T2Decision {
  decision: 'SUPPRESS' | 'RETRIEVE';
  confidence: number;
  reasoning: string;
}

class T2LLMGatingTier {
  async decide(
    currentUtterance: string,
    previousUtterance: string,
    context: string
  ): Promise<T2Decision> {
    // Simulated LLM call - in production, call your LLM API
    // This would use prompt engineering to determine if new retrieval needed
    return new Promise((resolve) => {
      // Simulate async LLM processing
      setTimeout(() => {
        const needs_retrieval = this.heuristicDecision(currentUtterance, previousUtterance);

        resolve({
          decision: needs_retrieval ? 'RETRIEVE' : 'SUPPRESS',
          confidence: 0.85,
          reasoning: needs_retrieval
            ? 'LLM determined new context needed'
            : 'LLM determined prior context sufficient',
        });
      }, 30); // Simulated latency
    });
  }

  private heuristicDecision(current: string, previous: string): boolean {
    // Simple heuristic: check if key entities differ
    const currentWords = new Set(current.toLowerCase().split(/\s+/));
    const previousWords = new Set(previous.toLowerCase().split(/\s+/));

    const keywordDifference = Math.abs(currentWords.size - previousWords.size);
    return keywordDifference > 3;
  }
}

// ============================================================================
// Presenter: Answer Suppression & Reuse
// ============================================================================

class Presenter {
  private priorAnswers: Map<string, string> = new Map();

  reusePriorAnswer(utteranceId: string, suppressedAnswerId: string): string | null {
    return this.priorAnswers.get(suppressedAnswerId) || null;
  }

  cacheAnswer(utteranceId: string, answer: string): void {
    this.priorAnswers.set(utteranceId, answer);
  }

  getAnswerByteForByte(utteranceId: string): string | null {
    return this.priorAnswers.get(utteranceId) || null;
  }

  getPriorAnswer(refUtteranceId: string): string | null {
    return this.priorAnswers.get(refUtteranceId) || null;
  }
}

// ============================================================================
// Cascade Controller
// ============================================================================

export class CascadeController extends EventEmitter {
  private t0: T0RuleBasedTier;
  private t1: T1DriftTier;
  private t2: T2LLMGatingTier;
  private cache: EvidenceCache;
  private presenter: Presenter;

  private turnState: Map<string, StreamingTurnState> = new Map();
  private utteranceSequence: Utterance[] = [];

  constructor() {
    super();
    this.t0 = new T0RuleBasedTier();
    this.t1 = new T1DriftTier();
    this.t2 = new T2LLMGatingTier();
    this.cache = new EvidenceCache();
    this.presenter = new Presenter();
  }

  /**
   * Main control flow: decision cascade T0 → T1 → (T2 if needed)
   */
  async decideRetrieval(
    currentUtterance: Utterance,
    previousUtterance?: Utterance
  ): Promise<ControllerDecision> {
    const startTime = performance.now();
    let tier: 'T0' | 'T1' | 'T2' = 'T0';
    let decision: 'SUPPRESS' | 'RETRIEVE' | 'CACHE_HIT' = 'RETRIEVE';
    let driftScore = 0;
    let confidence = 0;
    let reason = '';
    let cacheHitId: string | undefined;
    let suppressedAnswerId: string | undefined;

    // ========== T0: Rule-Based ==========
    const t0_result = this.t0.decide(currentUtterance, previousUtterance);

    if (t0_result.decision === 'SUPPRESS') {
      tier = 'T0';
      decision = 'SUPPRESS';
      confidence = t0_result.confidence;
      reason = t0_result.reason;
      suppressedAnswerId = previousUtterance?.id;

      const latencyMs = performance.now() - startTime;
      this.emitDecision({
        tier,
        decision,
        driftScore: 0,
        confidence,
        reason,
        suppressedAnswerId,
        timestamp: Date.now(),
        latencyMs,
      });

      return {
        tier,
        decision,
        driftScore: 0,
        confidence,
        reason,
        suppressedAnswerId,
        timestamp: Date.now(),
        latencyMs,
      };
    }

    // ========== Cache Check ==========
    if (currentUtterance.embedding) {
      const cachedEvidence = this.cache.get(currentUtterance.id, currentUtterance.embedding);
      if (cachedEvidence) {
        tier = 'T1';
        decision = 'CACHE_HIT';
        confidence = 0.95;
        reason = 'CACHE_HIT_ON_SIMILARITY';
        cacheHitId = cachedEvidence.id;

        const latencyMs = performance.now() - startTime;
        this.emitDecision({
          tier,
          decision,
          driftScore: 0.18, // 1 - similarity threshold
          confidence,
          reason,
          cacheHitId,
          timestamp: Date.now(),
          latencyMs,
        });

        return {
          tier,
          decision,
          driftScore: 0.18,
          confidence,
          reason,
          cacheHitId,
          timestamp: Date.now(),
          latencyMs,
        };
      }
    }

    // ========== T1: Drift-Based ==========
    const t1_result = this.t1.decide(
      currentUtterance.embedding,
      previousUtterance?.embedding
    );
    driftScore = t1_result.driftScore;

    if (t1_result.decision === 'SUPPRESS') {
      tier = 'T1';
      decision = 'SUPPRESS';
      confidence = t1_result.confidence;
      reason = t1_result.reason;

      const latencyMs = performance.now() - startTime;
      this.emitDecision({
        tier,
        decision,
        driftScore,
        confidence,
        reason,
        timestamp: Date.now(),
        latencyMs,
      });

      return {
        tier,
        decision,
        driftScore,
        confidence,
        reason,
        timestamp: Date.now(),
        latencyMs,
      };
    }

    // ========== T2: LLM-Based (if escalated) ==========
    if (t1_result.decision === 'ESCALATE' && previousUtterance) {
      const t2_result = await this.t2.decide(
        currentUtterance.text,
        previousUtterance.text,
        '' // context
      );

      tier = 'T2';
      decision = t2_result.decision === 'SUPPRESS' ? 'SUPPRESS' : 'RETRIEVE';
      confidence = t2_result.confidence;
      reason = t2_result.reasoning;
    }

    const latencyMs = performance.now() - startTime;
    this.emitDecision({
      tier,
      decision,
      driftScore,
      confidence,
      reason,
      timestamp: Date.now(),
      latencyMs,
    });

    return {
      tier,
      decision,
      driftScore,
      confidence,
      reason,
      timestamp: Date.now(),
      latencyMs,
    };
  }

  /**
   * Streaming Turn State Machine
   */
  initializeTurn(utteranceId: string): StreamingTurnState {
    const state: StreamingTurnState = {
      utteranceId,
      currentEpoch: 'WAIT',
      chunkBuffer: [],
      chunkIndex: 0,
      early_retrieval_started: false,
      started_at: Date.now(),
    };

    this.turnState.set(utteranceId, state);
    this.emit('turn:initialized', { utteranceId, state });

    return state;
  }

  /**
   * Advance state machine: WAIT → PROVISIONAL → COMMIT → UTTERANCE_END
   */
  transitionEpoch(utteranceId: string, newEpoch: StreamingEpoch['epoch']): StreamingTurnState | null {
    const state = this.turnState.get(utteranceId);
    if (!state) return null;

    const previousEpoch = state.currentEpoch;
    state.currentEpoch = newEpoch;

    // Early retrieval starts at COMMIT
    if (newEpoch === 'COMMIT' && !state.early_retrieval_started) {
      state.early_retrieval_started = true;
      this.emit('retrieval:early_start', { utteranceId, epoch: 'COMMIT' });
    }

    this.emit('epoch:transition', {
      utteranceId,
      from: previousEpoch,
      to: newEpoch,
      timestamp: Date.now(),
    });

    return state;
  }

  addChunk(utteranceId: string, chunk: string): StreamingTurnState | null {
    const state = this.turnState.get(utteranceId);
    if (!state) return null;

    state.chunkBuffer.push(chunk);
    state.chunkIndex++;

    return state;
  }

  /**
   * Early retrieval at COMMIT epoch
   */
  async startEarlyRetrieval(
    utteranceId: string,
    utterance: Utterance,
    previousUtterance?: Utterance
  ): Promise<ControllerDecision | null> {
    const state = this.turnState.get(utteranceId);
    if (!state || state.currentEpoch !== 'COMMIT') return null;

    const decision = await this.decideRetrieval(utterance, previousUtterance);
    state.controller_decision = decision;

    // Emit with latency tracking
    this.emit('controller:decision', {
      utteranceId,
      decision,
      epoch: 'COMMIT',
      timestamp: Date.now(),
    });

    return decision;
  }

  /**
   * Store retrieved evidence and cache it
   */
  storeRetrievedEvidence(utteranceId: string, evidence: Omit<CachedEvidence, 'id' | 'timestamp'>): void {
    const state = this.turnState.get(utteranceId);
    if (!state) return;

    const cachedEvidence: CachedEvidence = {
      id: `evidence_${utteranceId}_${Date.now()}`,
      timestamp: Date.now(),
      retrievedAt: Date.now(),
      reusedCount: 0,
      ...evidence,
    };

    this.cache.put(cachedEvidence);
    state.retrieved_evidence = cachedEvidence;

    this.emit('evidence:cached', {
      utteranceId,
      evidence: cachedEvidence,
    });
  }

  /**
   * Suppression path: Reuse prior answer byte-for-byte
   */
  suppressAndReuse(utteranceId: string, priorUtteranceId: string): string | null {
    const priorAnswer = this.presenter.getPriorAnswer(priorUtteranceId);
    if (!priorAnswer) return null;

    const state = this.turnState.get(utteranceId);
    if (state) {
      state.presented_answer = priorAnswer;
    }

    this.emit('suppression:answer_reused', {
      utteranceId,
      priorUtteranceId,
      answerLength: priorAnswer.length,
    });

    return priorAnswer;
  }

  /**
   * Complete turn: move to UTTERANCE_END
   */
  completeTurn(utteranceId: string, finalAnswer: string): void {
    const state = this.turnState.get(utteranceId);
    if (!state) return;

    state.currentEpoch = 'UTTERANCE_END';
    this.presenter.cacheAnswer(utteranceId, finalAnswer);

    const duration = Date.now() - state.started_at;

    this.emit('turn:complete', {
      utteranceId,
      duration,
      chunks: state.chunkIndex,
      decision: state.controller_decision,
      cached: !!state.retrieved_evidence,
    });

    // Cleanup
    setTimeout(() => {
      this.turnState.delete(utteranceId);
    }, 100);
  }

  /**
   * Utility: Get current turn state
   */
  getTurnState(utteranceId: string): StreamingTurnState | undefined {
    return this.turnState.get(utteranceId);
  }

  /**
   * Utility: Get cache statistics
   */
  getCacheStats() {
    return this.cache.stats();
  }

  /**
   * Utility: Record rule-based facts
   */
  recordUtterance(utterance: Utterance): void {
    this.t0.recordUtterance(utterance);
    this.utteranceSequence.push(utterance);
  }

  /**
   * Emit controller decision events
   */
  private emitDecision(decision: ControllerDecision): void {
    this.emit('controller:decision', decision);
  }
}

export { EvidenceCache, T0RuleBasedTier, T1DriftTier, T2LLMGatingTier, Presenter };
