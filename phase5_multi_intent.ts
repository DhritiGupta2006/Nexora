/**
 * PHASE 5: Multi-Intent Planner, Parallel Retrieval & Per-Sub-Intent Uncertainty
 * 
 * Features:
 * - Multi-intent gate (coordination, request clauses, list cues)
 * - Query planner with LLM + spaCy fallback (1.5s timeout)
 * - Slot injection (place, quantity, date) for self-containment
 * - Merge near-duplicate sub-queries (cos ≥ 0.92)
 * - Parallel per-sub-query retrieval (4 per sub-query, 12 global)
 * - Per-sub-intent gate, drafting, verification, uncertainty
 * - LLM semaphore (3 concurrent max)
 * - Multi-sub-intent ledger and PDF-shaped output
 * - Stream answer chunks in sub-intent order
 */

import { EventEmitter } from 'events';

// ============================================================================
// Types & Interfaces
// ============================================================================

export interface SubQuery {
  id: string;
  text: string;
  embedding: number[];
  intent: string;
  slots: {
    place?: string;
    quantity?: string;
    date?: string;
  };
  source?: 'llm' | 'fallback' | 'single';
  confidence: number;
  timestamp: number;
}

export interface RetrievalResult {
  id: string;
  subQueryId: string;
  sources: RetrievalSource[];
  metadata: {
    retrievedAt: number;
    latencyMs: number;
    sourceCount: number;
  };
}

export interface RetrievalSource {
  id: string;
  title: string;
  snippet: string;
  confidence: number;
  relevance?: number;
}

export interface SubIntentDraft {
  subQueryId: string;
  text: string;
  confidence: number;
  uncertainty_flags: string[];
  missing_topics: string[];
  draft_latencyMs: number;
  timestamp: number;
}

export interface SubIntentVerification {
  subQueryId: string;
  isValid: boolean;
  gaps: string[];
  suggestions: string[];
  verification_latencyMs: number;
}

export interface SubIntentUncertainty {
  subQueryId: string;
  confidence_score: number; // 0-1
  missing_data: string[];
  needs_clarification: boolean;
  suggested_followup?: string;
}

export interface AnswerChunk {
  id: string;
  subQueryId: string;
  subQueryText: string;
  answer: string;
  sources: RetrievalSource[];
  uncertainty: SubIntentUncertainty;
  chunk_index: number;
  timestamp: number;
}

export interface MultiSubIntentLedger {
  utteranceId: string;
  originalText: string;
  subQueries: SubQuery[];
  retrievalResults: Map<string, RetrievalResult>;
  drafts: Map<string, SubIntentDraft>;
  verifications: Map<string, SubIntentVerification>;
  uncertainties: Map<string, SubIntentUncertainty>;
  answerChunks: AnswerChunk[];
  processing_stats: {
    total_latencyMs: number;
    parallel_latencyMs: number;
    time_saved_ms: number;
    sub_query_count: number;
    total_sources: number;
  };
}

export interface TurnOutput {
  utteranceId: string;
  originalUtterance: string;
  multi_intent: boolean;
  sub_query_count: number;
  sub_queries: SubQuery[];
  answer_chunks: AnswerChunk[];
  final_answer: string;
  ledger: MultiSubIntentLedger;
  metadata: {
    started_at: number;
    completed_at: number;
    total_duration_ms: number;
    is_parallel: boolean;
  };
}

// ============================================================================
// Multi-Intent Gate
// ============================================================================

class MultiIntentGate {
  private coordination_markers = /\b(and|but|also|moreover|furthermore|however|yet|or|plus|besides)\b/gi;
  private request_clauses = /\b(provide|give me|show|list|enumerate|compare|contrast|analyze|explain|describe)\b/gi;
  private list_cues = /\b(multiple|several|different|various|list of|set of|collection of)\b/gi;

  detect(text: string): {
    isMultiIntent: boolean;
    indicators: {
      coordination: boolean;
      requestClauses: boolean;
      listCues: boolean;
      confidence: number;
    };
  } {
    const lower = text.toLowerCase();

    const hasCoordination = this.coordination_markers.test(lower);
    const hasRequestClauses = this.request_clauses.test(lower);
    const hasListCues = this.list_cues.test(lower);

    const isMultiIntent = hasCoordination || hasRequestClauses || hasListCues;
    const confidence = (Number(hasCoordination) +
      Number(hasRequestClauses) +
      Number(hasListCues)) / 3;

    return {
      isMultiIntent,
      indicators: {
        coordination: hasCoordination,
        requestClauses: hasRequestClauses,
        listCues: hasListCues,
        confidence,
      },
    };
  }
}

// ============================================================================
// Query Planner: LLM + spaCy Fallback
// ============================================================================

interface PlannerOutput {
  subQueries: string[];
  source: 'llm' | 'fallback' | 'single';
  confidence: number;
  planningLatencyMs: number;
}

class QueryPlanner {
  private readonly PLANNER_TIMEOUT_MS = 1500;

  async plan(utterance: string): Promise<PlannerOutput> {
    const startTime = performance.now();

    // Try LLM planner with timeout
    try {
      const llmResult = await Promise.race([
        this.callLLMPlanner(utterance),
        this.timeoutPromise(this.PLANNER_TIMEOUT_MS),
      ]);

      const planningLatencyMs = performance.now() - startTime;
      return {
        subQueries: llmResult,
        source: 'llm',
        confidence: 0.95,
        planningLatencyMs,
      };
    } catch (error) {
      // Fallback to spaCy-based extraction
      return {
        subQueries: this.spaCyFallback(utterance),
        source: 'fallback',
        confidence: 0.75,
        planningLatencyMs: performance.now() - startTime,
      };
    }
  }

  private async callLLMPlanner(utterance: string): Promise<string[]> {
    // Simulated LLM call - in production, use real LLM API
    return new Promise((resolve) => {
      setTimeout(() => {
        // Simple decomposition logic
        const parts = utterance
          .split(/\band\b|\bbut\b|\balso\b/i)
          .map((s) => s.trim())
          .filter((s) => s.length > 10);

        resolve(parts.length > 1 ? parts : [utterance]);
      }, 50); // Simulated latency
    });
  }

  private spaCyFallback(utterance: string): string[] {
    // spaCy-like sentence segmentation fallback
    const sentences = utterance.split(/[.!?]+/).filter((s) => s.trim().length > 10);

    if (sentences.length > 1) {
      return sentences.map((s) => s.trim());
    }

    // Split on coordination markers
    const parts = utterance
      .split(/\b(and|but|also|or)\b/i)
      .filter((s) => !/(and|but|also|or)/i.test(s) && s.trim().length > 10)
      .map((s) => s.trim());

    return parts.length > 1 ? parts : [utterance];
  }

  private timeoutPromise(ms: number): Promise<never> {
    return new Promise((_, reject) => {
      setTimeout(() => reject(new Error('LLM planner timeout')), ms);
    });
  }
}

// ============================================================================
// Sub-Query Post-Processor
// ============================================================================

interface SlotExtraction {
  place?: string;
  quantity?: string;
  date?: string;
}

class SubQueryProcessor {
  private readonly SIMILARITY_THRESHOLD = 0.92;
  private readonly MIN_LENGTH = 8; // minimum words
  private readonly MAX_SUB_QUERIES = 4;

  /**
   * Post-process and normalize sub-queries
   */
  process(
    subQueryTexts: string[],
    embeddings: number[][],
    globalSlots: SlotExtraction
  ): SubQuery[] {
    // 1. Slot injection: add context to each sub-query
    let processed = subQueryTexts.map((text, idx) => ({
      id: `sub_query_${idx}`,
      text: this.injectSlots(text, globalSlots),
      embedding: embeddings[idx] || [],
      slots: globalSlots,
      confidence: 1.0,
      timestamp: Date.now(),
    }));

    // 2. Merge near-duplicate sub-queries (cos ≥ 0.92)
    processed = this.mergeDuplicates(processed);

    // 3. Drop short sub-queries
    processed = processed.filter((q) => q.text.split(' ').length >= this.MIN_LENGTH);

    // 4. Cap at MAX_SUB_QUERIES
    processed = processed.slice(0, this.MAX_SUB_QUERIES);

    return processed;
  }

  private injectSlots(text: string, slots: SlotExtraction): string {
    let enhanced = text;

    if (slots.place && !text.toLowerCase().includes(slots.place.toLowerCase())) {
      enhanced += ` in ${slots.place}`;
    }

    if (slots.quantity && !text.toLowerCase().includes(slots.quantity.toLowerCase())) {
      enhanced += ` (${slots.quantity})`;
    }

    if (slots.date && !text.toLowerCase().includes(slots.date.toLowerCase())) {
      enhanced += ` on ${slots.date}`;
    }

    return enhanced;
  }

  private mergeDuplicates(subQueries: SubQuery[]): SubQuery[] {
    const merged: SubQuery[] = [];
    const seen = new Set<number>();

    for (let i = 0; i < subQueries.length; i++) {
      if (seen.has(i)) continue;

      const current = subQueries[i];
      const duplicates = [i];

      for (let j = i + 1; j < subQueries.length; j++) {
        if (seen.has(j)) continue;

        const similarity = this.cosineSimilarity(current.embedding, subQueries[j].embedding);
        if (similarity >= this.SIMILARITY_THRESHOLD) {
          duplicates.push(j);
          seen.add(j);
        }
      }

      // Merge duplicates into one
      if (duplicates.length > 1) {
        current.text = subQueries
          .filter((_, idx) => duplicates.includes(idx))
          .map((q) => q.text)
          .join('; ');
      }

      merged.push(current);
      seen.add(i);
    }

    return merged;
  }

  private cosineSimilarity(a: number[], b: number[]): number {
    if (a.length !== b.length || a.length === 0) return 0;

    let dotProduct = 0;
    let normA = 0;
    let normB = 0;

    for (let i = 0; i < a.length; i++) {
      dotProduct += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }

    const denominator = Math.sqrt(normA) * Math.sqrt(normB);
    return denominator === 0 ? 0 : dotProduct / denominator;
  }
}

// ============================================================================
// Parallel Retriever with Quotas
// ============================================================================

class ParallelRetriever {
  private readonly SOURCES_PER_SUB_QUERY = 4;
  private readonly GLOBAL_QUOTA = 12;
  private globalSourcesUsed = 0;

  async retrieveParallel(
    subQueries: SubQuery[]
  ): Promise<Map<string, RetrievalResult>> {
    const retrievalTasks = subQueries.map((sq) =>
      this.retrieveForSubQuery(sq).catch((err) => {
        console.warn(`Retrieval failed for ${sq.id}:`, err);
        return {
          id: `retrieval_${sq.id}`,
          subQueryId: sq.id,
          sources: [],
          metadata: {
            retrievedAt: Date.now(),
            latencyMs: 0,
            sourceCount: 0,
          },
        };
      })
    );

    const results = await Promise.all(retrievalTasks);
    const resultMap = new Map<string, RetrievalResult>();

    for (const result of results) {
      resultMap.set(result.subQueryId, result);
    }

    return resultMap;
  }

  private async retrieveForSubQuery(subQuery: SubQuery): Promise<RetrievalResult> {
    const startTime = performance.now();

    // Simulate retrieval with quota check
    const quota = Math.min(
      this.SOURCES_PER_SUB_QUERY,
      this.GLOBAL_QUOTA - this.globalSourcesUsed
    );

    const sources = await this.mockRetrieve(subQuery.text, quota);
    this.globalSourcesUsed += sources.length;

    return {
      id: `retrieval_${subQuery.id}`,
      subQueryId: subQuery.id,
      sources,
      metadata: {
        retrievedAt: Date.now(),
        latencyMs: performance.now() - startTime,
        sourceCount: sources.length,
      },
    };
  }

  private async mockRetrieve(query: string, quota: number): Promise<RetrievalSource[]> {
    // Simulated retrieval
    return new Promise((resolve) => {
      setTimeout(() => {
        const sources: RetrievalSource[] = [];
        for (let i = 0; i < Math.min(quota, 3); i++) {
          sources.push({
            id: `src_${query.substring(0, 10)}_${i}`,
            title: `Source ${i + 1} for "${query.substring(0, 30)}"`,
            snippet: `Relevant content about ${query}...`,
            confidence: 0.85 - i * 0.05,
          });
        }
        resolve(sources);
      }, 100);
    });
  }

  reset(): void {
    this.globalSourcesUsed = 0;
  }
}

// ============================================================================
// Per-Sub-Intent Processing: Gate, Draft, Verify, Uncertainty
// ============================================================================

class SubIntentProcessor {
  private draftingSemaphore = 3; // Max 3 concurrent LLM calls
  private activeDecoder = 0;

  async gateCheck(subQuery: SubQuery): Promise<{ isValid: boolean; reason?: string }> {
    // Gate check: validate sub-query is meaningful
    if (subQuery.text.length < 10) {
      return { isValid: false, reason: 'Too short' };
    }

    if (subQuery.slots.place || subQuery.slots.date || subQuery.slots.quantity) {
      return { isValid: true };
    }

    return { isValid: true };
  }

  async draft(subQuery: SubQuery): Promise<SubIntentDraft> {
    // Wait for semaphore slot
    await this.acquireSemaphore();

    try {
      const startTime = performance.now();

      // Simulated draft generation
      const answer = `Answer for: ${subQuery.text}`;
      const uncertainty_flags = this.extractUncertaintyFlags(subQuery.text);
      const missing_topics = this.detectMissingTopics(subQuery.text);

      return {
        subQueryId: subQuery.id,
        text: answer,
        confidence: 0.85,
        uncertainty_flags,
        missing_topics,
        draft_latencyMs: performance.now() - startTime,
        timestamp: Date.now(),
      };
    } finally {
      this.releaseSemaphore();
    }
  }

  async verify(
    subQuery: SubQuery,
    draft: SubIntentDraft
  ): Promise<SubIntentVerification> {
    const startTime = performance.now();

    // Verification: check completeness and consistency
    const gaps: string[] = [];
    const suggestions: string[] = [];

    if (subQuery.slots.date && !draft.text.includes(subQuery.slots.date)) {
      gaps.push('Date context missing in answer');
      suggestions.push(`Add temporal context: ${subQuery.slots.date}`);
    }

    if (subQuery.slots.place && !draft.text.includes(subQuery.slots.place)) {
      gaps.push('Location context missing');
      suggestions.push(`Add location: ${subQuery.slots.place}`);
    }

    return {
      subQueryId: subQuery.id,
      isValid: gaps.length === 0,
      gaps,
      suggestions,
      verification_latencyMs: performance.now() - startTime,
    };
  }

  scoreUncertainty(
    subQuery: SubQuery,
    draft: SubIntentDraft,
    verification: SubIntentVerification
  ): SubIntentUncertainty {
    let confidenceScore = draft.confidence;

    // Reduce confidence based on gaps
    confidenceScore -= verification.gaps.length * 0.1;

    // Reduce confidence based on missing topics
    confidenceScore -= draft.missing_topics.length * 0.05;

    confidenceScore = Math.max(0, Math.min(1, confidenceScore));

    const needsClarification = confidenceScore < 0.7;

    return {
      subQueryId: subQuery.id,
      confidence_score: confidenceScore,
      missing_data: verification.gaps,
      needs_clarification: needsClarification,
      suggested_followup: needsClarification
        ? `Clarify: ${subQuery.text}?`
        : undefined,
    };
  }

  private async acquireSemaphore(): Promise<void> {
    while (this.activeDecoder >= this.draftingSemaphore) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    this.activeDecoder++;
  }

  private releaseSemaphore(): void {
    this.activeDecoder--;
  }

  private extractUncertaintyFlags(text: string): string[] {
    const flags: string[] = [];

    if (/\?/.test(text)) flags.push('contains_question');
    if (/\b(might|may|could|possibly|perhaps)\b/i.test(text))
      flags.push('conditional_language');
    if (/\b(unclear|ambiguous|vague)\b/i.test(text)) flags.push('ambiguous_terms');

    return flags;
  }

  private detectMissingTopics(text: string): string[] {
    const topics: string[] = [];

    if (/\bwhy\b/i.test(text) && !text.includes('reason')) {
      topics.push('reasoning');
    }

    if (/\bhow\b/i.test(text) && !text.includes('process')) {
      topics.push('process');
    }

    if (/\bwhen\b/i.test(text) && !text.includes('time')) {
      topics.push('temporal_context');
    }

    return topics;
  }
}

// ============================================================================
// Multi-Intent Orchestrator (Main Phase 5 Class)
// ============================================================================

export class MultiIntentPlanner extends EventEmitter {
  private gate: MultiIntentGate;
  private planner: QueryPlanner;
  private processor: SubQueryProcessor;
  private retriever: ParallelRetriever;
  private subIntentProcessor: SubIntentProcessor;

  constructor() {
    super();
    this.gate = new MultiIntentGate();
    this.planner = new QueryPlanner();
    this.processor = new SubQueryProcessor();
    this.retriever = new ParallelRetriever();
    this.subIntentProcessor = new SubIntentProcessor();
  }

  /**
   * Main orchestration: Detect multi-intent → Plan → Retrieve → Process
   */
  async process(utterance: string, embedding: number[]): Promise<TurnOutput> {
    const utteranceId = `utt_${Date.now()}`;
    const startTime = performance.now();

    // Step 1: Detect multi-intent
    const intentDetection = this.gate.detect(utterance);
    const isMultiIntent = intentDetection.isMultiIntent;

    this.emit('intent:detected', {
      utteranceId,
      isMultiIntent,
      indicators: intentDetection.indicators,
    });

    // Step 2: Plan sub-queries
    let subQueries: SubQuery[];
    let plannerOutput: PlannerOutput;

    if (isMultiIntent) {
      plannerOutput = await this.planner.plan(utterance);
      const globalSlots = this.extractGlobalSlots(utterance);

      subQueries = this.processor.process(
        plannerOutput.subQueries,
        plannerOutput.subQueries.map(() => embedding), // Use same embedding for all
        globalSlots
      );

      for (const sq of subQueries) {
        sq.source = plannerOutput.source;
      }

      this.emit('planning:complete', {
        utteranceId,
        subQueryCount: subQueries.length,
        source: plannerOutput.source,
        latencyMs: plannerOutput.planningLatencyMs,
      });
    } else {
      // Single intent: treat as single sub-query
      subQueries = [
        {
          id: 'sub_query_0',
          text: utterance,
          embedding,
          intent: 'single',
          slots: {},
          source: 'single',
          confidence: 1.0,
          timestamp: Date.now(),
        },
      ];
    }

    // Step 3: Parallel retrieval
    const retrievalStartTime = performance.now();
    const retrievalResults = await this.retriever.retrieveParallel(subQueries);
    const retrievalLatency = performance.now() - retrievalStartTime;

    this.emit('retrieval:complete', {
      utteranceId,
      subQueryCount: subQueries.length,
      totalSources: Array.from(retrievalResults.values()).reduce(
        (sum, r) => sum + r.sources.length,
        0
      ),
      latencyMs: retrievalLatency,
    });

    // Step 4: Parallel per-sub-intent processing
    const processingTasks = subQueries.map((sq) => this.processSubIntent(sq, retrievalResults));
    const processingResults = await Promise.all(processingTasks);

    const drafts = new Map<string, SubIntentDraft>();
    const verifications = new Map<string, SubIntentVerification>();
    const uncertainties = new Map<string, SubIntentUncertainty>();
    const answerChunks: AnswerChunk[] = [];

    for (const result of processingResults) {
      drafts.set(result.draft.subQueryId, result.draft);
      verifications.set(result.verification.subQueryId, result.verification);
      uncertainties.set(result.uncertainty.subQueryId, result.uncertainty);

      // Emit answer chunk in order
      const chunk: AnswerChunk = {
        id: `chunk_${result.draft.subQueryId}`,
        subQueryId: result.draft.subQueryId,
        subQueryText: subQueries.find((sq) => sq.id === result.draft.subQueryId)?.text || '',
        answer: result.draft.text,
        sources: retrievalResults.get(result.draft.subQueryId)?.sources || [],
        uncertainty: result.uncertainty,
        chunk_index: answerChunks.length,
        timestamp: Date.now(),
      };

      answerChunks.push(chunk);
      this.emit('answer:chunk', chunk);
    }

    // Step 5: Build multi-sub-intent ledger
    const ledger: MultiSubIntentLedger = {
      utteranceId,
      originalText: utterance,
      subQueries,
      retrievalResults,
      drafts,
      verifications,
      uncertainties,
      answerChunks,
      processing_stats: {
        total_latencyMs: performance.now() - startTime,
        parallel_latencyMs: Math.max(retrievalLatency, 500), // Approximate
        time_saved_ms: isMultiIntent ? (subQueries.length - 1) * 100 : 0,
        sub_query_count: subQueries.length,
        total_sources: Array.from(retrievalResults.values()).reduce(
          (sum, r) => sum + r.sources.length,
          0
        ),
      },
    };

    // Step 6: Build PDF-shaped TurnOutput
    const finalAnswer = answerChunks
      .map((chunk) => `[${chunk.subQueryText}]: ${chunk.answer}`)
      .join('\n\n');

    const output: TurnOutput = {
      utteranceId,
      originalUtterance: utterance,
      multi_intent: isMultiIntent,
      sub_query_count: subQueries.length,
      sub_queries: subQueries,
      answer_chunks: answerChunks,
      final_answer: finalAnswer,
      ledger,
      metadata: {
        started_at: startTime,
        completed_at: Date.now(),
        total_duration_ms: performance.now() - startTime,
        is_parallel: isMultiIntent,
      },
    };

    this.emit('processing:complete', {
      utteranceId,
      totalDurationMs: output.metadata.total_duration_ms,
      isParallel: output.metadata.is_parallel,
      subQueryCount: output.sub_query_count,
    });

    return output;
  }

  private async processSubIntent(
    subQuery: SubQuery,
    retrievalResults: Map<string, RetrievalResult>
  ): Promise<{
    draft: SubIntentDraft;
    verification: SubIntentVerification;
    uncertainty: SubIntentUncertainty;
  }> {
    // Gate check
    const gateResult = await this.subIntentProcessor.gateCheck(subQuery);
    if (!gateResult.isValid) {
      console.warn(`Sub-query gating failed: ${gateResult.reason}`);
    }

    // Parallel: drafting + verification
    const [draft, verification] = await Promise.all([
      this.subIntentProcessor.draft(subQuery),
      this.subIntentProcessor.verify(subQuery, {} as any), // Placeholder
    ]);

    // Re-verify with draft
    const finalVerification = await this.subIntentProcessor.verify(subQuery, draft);

    // Score uncertainty
    const uncertainty = this.subIntentProcessor.scoreUncertainty(
      subQuery,
      draft,
      finalVerification
    );

    return {
      draft,
      verification: finalVerification,
      uncertainty,
    };
  }

  private extractGlobalSlots(utterance: string): { place?: string; quantity?: string; date?: string } {
    const slots: { place?: string; quantity?: string; date?: string } = {};

    // Simple extraction - in production would use NER
    const placeMatch = utterance.match(/\b(?:in|at|near|around)\s+(\w+)/i);
    if (placeMatch) slots.place = placeMatch[1];

    const quantityMatch = utterance.match(/(\w+\s+(?:items|things|entries|results))/i);
    if (quantityMatch) slots.quantity = quantityMatch[1];

    const dateMatch = utterance.match(
      /\b(?:on|for|by|since|until)\s+(\d{1,2}\/\d{1,2}\/\d{4}|\w+\s+\d{1,2})/i
    );
    if (dateMatch) slots.date = dateMatch[1];

    return slots;
  }
}

export {
  MultiIntentGate,
  QueryPlanner,
  SubQueryProcessor,
  ParallelRetriever,
  SubIntentProcessor,
};
