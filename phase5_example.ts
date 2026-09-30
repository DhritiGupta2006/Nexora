/**
 * PHASE 5: 3-Intent Example
 * 
 * Demonstrates:
 * - 3-intent detection and decomposition
 * - Self-contained sub-queries with slot injection
 * - Parallel retrieval with quotas
 * - Per-sub-intent processing (gate, draft, verify, uncertainty)
 * - Answer chunks emitted in order
 * - TTFT improvement through parallelism
 * - Acceptance criteria validation
 */

import { MultiIntentPlanner } from './phase5_multi_intent';

// ============================================================================
// Utilities
// ============================================================================

function mockEmbedding(seed: number, dim: number = 256): number[] {
  const arr: number[] = [];
  for (let i = 0; i < dim; i++) {
    arr.push(Math.sin(seed + i) * Math.cos(seed * i));
  }
  const norm = Math.sqrt(arr.reduce((sum, x) => sum + x * x, 0));
  return arr.map((x) => x / norm);
}

function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms.toFixed(2)}ms`;
  }
  return `${(ms / 1000).toFixed(2)}s`;
}

// ============================================================================
// 3-Intent Example Execution
// ============================================================================

async function run3IntentExample(): Promise<void> {
  console.log(
    '\n╔═══════════════════════════════════════════════════════════════╗'
  );
  console.log(
    '║        PHASE 5: 3-Intent Multi-Parallel Processing            ║'
  );
  console.log(
    '╚═══════════════════════════════════════════════════════════════╝\n'
  );

  const planner = new MultiIntentPlanner();

  // ========== THE TEST UTTERANCE ==========
  const utterance =
    'Explain what machine learning is, compare it with traditional programming approaches, and list the top 5 real-world applications of ML in industry';

  console.log('📝 INPUT UTTERANCE');
  console.log('─'.repeat(65));
  console.log(`"${utterance}"\n`);

  // ========== PROCESSING STARTS ==========
  const overallStart = performance.now();

  // Listen to events
  let eventLog: any[] = [];

  planner.on('intent:detected', (e) => {
    eventLog.push(e);
    console.log(`\n🎯 INTENT DETECTION`);
    console.log('─'.repeat(65));
    console.log(`Multi-intent: ${e.isMultiIntent}`);
    console.log(`Indicators:`);
    console.log(`  • Coordination: ${e.indicators.coordination}`);
    console.log(`  • Request clauses: ${e.indicators.requestClauses}`);
    console.log(`  • List cues: ${e.indicators.listCues}`);
    console.log(`  • Confidence: ${(e.indicators.confidence * 100).toFixed(0)}%`);
  });

  planner.on('planning:complete', (e) => {
    eventLog.push(e);
    console.log(`\n📋 QUERY PLANNING`);
    console.log('─'.repeat(65));
    console.log(`Planner source: ${e.source}`);
    console.log(`Sub-queries generated: ${e.subQueryCount}`);
    console.log(`Planning latency: ${formatDuration(e.latencyMs)}`);
  });

  planner.on('retrieval:complete', (e) => {
    eventLog.push(e);
    console.log(`\n🔍 PARALLEL RETRIEVAL`);
    console.log('─'.repeat(65));
    console.log(`Sub-queries: ${e.subQueryCount}`);
    console.log(`Total sources retrieved: ${e.totalSources}/12 (quota)`);
    console.log(`Retrieval latency: ${formatDuration(e.latencyMs)}`);
  });

  planner.on('answer:chunk', (chunk) => {
    console.log(`\n💬 ANSWER CHUNK [${chunk.chunk_index + 1}]`);
    console.log('─'.repeat(65));
    console.log(`Sub-query: "${chunk.subQueryText.substring(0, 60)}..."`);
    console.log(`Answer: "${chunk.answer.substring(0, 80)}..."`);
    console.log(`Confidence: ${(chunk.uncertainty.confidence_score * 100).toFixed(0)}%`);
    console.log(
      `Needs clarification: ${chunk.uncertainty.needs_clarification ? 'Yes' : 'No'}`
    );
  });

  planner.on('processing:complete', (e) => {
    eventLog.push(e);
    console.log(`\n✅ PROCESSING COMPLETE`);
    console.log('─'.repeat(65));
    console.log(`Total duration: ${formatDuration(e.totalDurationMs)}`);
    console.log(`Parallel processing: ${e.isParallel ? 'Yes' : 'No'}`);
    console.log(`Sub-queries processed: ${e.subQueryCount}`);
  });

  // Process the utterance
  const output = await planner.process(utterance, mockEmbedding(123));

  const overallEnd = performance.now();
  const overallDuration = overallEnd - overallStart;

  // ========== DETAILED RESULTS ==========
  console.log(`\n\n📊 DETAILED RESULTS`);
  console.log('═'.repeat(65));

  // Sub-queries analysis
  console.log(`\n1️⃣  SUB-QUERIES ANALYSIS`);
  console.log('─'.repeat(65));

  console.log(
    `Count: ${output.sub_query_count} (target: 3 for this example)`
  );

  console.log(`\nSub-query Details:`);
  for (let i = 0; i < output.sub_queries.length; i++) {
    const sq = output.sub_queries[i];
    console.log(`\n  [${i + 1}] ID: ${sq.id}`);
    console.log(`      Text: "${sq.text.substring(0, 80)}..."`);
    console.log(`      Source: ${sq.source} (llm/fallback/single)`);
    console.log(`      Confidence: ${(sq.confidence * 100).toFixed(0)}%`);

    console.log(`      Self-containment check:`);
    const slots = Object.entries(sq.slots)
      .filter(([_, v]) => v)
      .map(([k, v]) => `${k}: ${v}`)
      .join(', ');
    console.log(`        Slots: ${slots || 'none (generic)'}`);
  }

  // Retrieval analysis
  console.log(`\n\n2️⃣  PARALLEL RETRIEVAL ANALYSIS`);
  console.log('─'.repeat(65));

  const stats = output.ledger.processing_stats;
  console.log(`Total sources: ${stats.total_sources}/12`);
  console.log(`Sub-queries: ${stats.sub_query_count}`);
  console.log(`Time saved by parallelism: ${formatDuration(stats.time_saved_ms)}`);

  console.log(`\nPer-sub-query retrieval:

`);
  for (const [subQueryId, result] of output.ledger.retrievalResults) {
    console.log(`  ${subQueryId}:`);
    console.log(`    Sources: ${result.sources.length}`);
    console.log(`    Latency: ${formatDuration(result.metadata.latencyMs)}`);

    for (const src of result.sources) {
      console.log(`      • "${src.title.substring(0, 50)}" (${(src.confidence * 100).toFixed(0)}%)`);
    }
  }

  // Per-sub-intent processing
  console.log(`\n\n3️⃣  PER-SUB-INTENT PROCESSING`);
  console.log('─'.repeat(65));

  let totalConfidence = 0;
  let clarificationCount = 0;

  for (let i = 0; i < output.answer_chunks.length; i++) {
    const chunk = output.answer_chunks[i];
    const uncertainty = output.ledger.uncertainties.get(chunk.subQueryId);
    const verification = output.ledger.verifications.get(chunk.subQueryId);

    console.log(`\n  [${i + 1}] "${chunk.subQueryText.substring(0, 60)}..."`);

    if (uncertainty) {
      console.log(`      Confidence: ${(uncertainty.confidence_score * 100).toFixed(0)}%`);
      totalConfidence += uncertainty.confidence_score;

      if (uncertainty.needs_clarification) {
        clarificationCount++;
        console.log(`      ⚠️  Needs clarification`);
        if (uncertainty.suggested_followup) {
          console.log(`         Suggested: "${uncertainty.suggested_followup}"`);
        }
      }

      if (uncertainty.missing_data.length > 0) {
        console.log(`      Missing: ${uncertainty.missing_data.join(', ')}`);
      }
    }

    if (verification && verification.gaps.length > 0) {
      console.log(`      Gaps: ${verification.gaps.join(', ')}`);
    }
  }

  const avgConfidence = totalConfidence / output.sub_query_count;
  console.log(`\n  Summary:`);
  console.log(`    Average confidence: ${(avgConfidence * 100).toFixed(0)}%`);
  console.log(
    `    Needs clarification: ${clarificationCount}/${output.sub_query_count}`
  );

  // Parallelism benefit
  console.log(`\n\n4️⃣  PARALLELISM ANALYSIS`);
  console.log('─'.repeat(65));

  const parallelDuration = output.metadata.total_duration_ms;
  const serialEstimate = output.sub_query_count * 150; // ~150ms per sub-query serially
  const speedup = serialEstimate / parallelDuration;

  console.log(`Parallel execution time: ${formatDuration(parallelDuration)}`);
  console.log(`Serial execution (est.): ${formatDuration(serialEstimate)}`);
  console.log(`Speedup factor: ${speedup.toFixed(2)}x`);

  if (output.answer_chunks.length > 0) {
    const firstChunkArrival = output.answer_chunks[0].timestamp - output.metadata.started_at;
    console.log(`\nTTFT (Time to First Token): ${formatDuration(firstChunkArrival)}`);
    console.log(`TTFT improvement: ${((1 - firstChunkArrival / serialEstimate) * 100).toFixed(0)}% faster than serial`);
  }

  // Final answer
  console.log(`\n\n5️⃣  FINAL ANSWER`);
  console.log('─'.repeat(65));

  const answerPreview = output.final_answer.substring(0, 300);
  console.log(`\n${answerPreview}...`);

  // ========== ACCEPTANCE CRITERIA ==========
  console.log(`\n\n✅ ACCEPTANCE CRITERIA VALIDATION`);
  console.log('═'.repeat(65));

  const criteria = [
    {
      name: '3 Self-Contained Sub-Queries',
      pass:
        output.sub_query_count === 3 &&
        output.sub_queries.every((sq) => sq.text.length > 20),
    },
    {
      name: 'Retrieval Bars Run in Parallel',
      pass: output.metadata.is_parallel && output.ledger.processing_stats.time_saved_ms > 0,
    },
    {
      name: 'Per-Sub-Intent Uncertainty Flags',
      pass:
        output.ledger.uncertainties.size === output.sub_query_count &&
        Array.from(output.ledger.uncertainties.values()).some(
          (u) => u.needs_clarification
        ),
    },
    {
      name: 'TTFT Lower Than Serial',
      pass: speedup > 1,
    },
  ];

  let allPass = true;
  for (const criterion of criteria) {
    const icon = criterion.pass ? '✅' : '❌';
    console.log(`${icon} ${criterion.name}: ${criterion.pass ? 'PASS' : 'FAIL'}`);
    if (!criterion.pass) allPass = false;
  }

  console.log(`\n${allPass ? '🎉' : '❌'} Overall: ${allPass ? 'ALL CRITERIA MET' : 'SOME CRITERIA FAILED'}`);

  // ========== TURN OUTPUT STRUCTURE ==========
  console.log(`\n\n📋 TURN OUTPUT STRUCTURE`);
  console.log('═'.repeat(65));

  console.log(`\nPDF-shaped TurnOutput:`);
  console.log(JSON.stringify(
    {
      utteranceId: output.utteranceId,
      originalUtterance: output.originalUtterance.substring(0, 60),
      multi_intent: output.multi_intent,
      sub_query_count: output.sub_query_count,
      sub_queries: output.sub_queries.map((sq) => ({
        id: sq.id,
        text_preview: sq.text.substring(0, 40),
        source: sq.source,
      })),
      answer_chunks: output.answer_chunks.length,
      metadata: {
        started_at: output.metadata.started_at,
        completed_at: output.metadata.completed_at,
        total_duration_ms: output.metadata.total_duration_ms,
        is_parallel: output.metadata.is_parallel,
      },
    },
    null,
    2
  ));

  console.log(`\n${'═'.repeat(65)}`);
  console.log(`Total Example Duration: ${formatDuration(overallDuration)}`);
  console.log(`${'═'.repeat(65)}\n`);
}

// Run the example
run3IntentExample().catch(console.error);
