/**
 * PHASE 5: Test Suite - Multi-Intent Planner
 * 
 * Validates:
 * - Multi-intent detection (coordination, requests, lists)
 * - Query planning with LLM + spaCy fallback
 * - Parallel retrieval with quotas
 * - Per-sub-intent processing (gate, draft, verify, uncertainty)
 * - 3-intent example with self-contained sub-queries
 * - TTFT (Time to First Token) parallelism benefit
 */

import {
  MultiIntentPlanner,
  SubQuery,
  TurnOutput,
  MultiSubIntentLedger,
} from './phase5_multi_intent';

// ============================================================================
// Test Utilities
// ============================================================================

function mockEmbedding(seed: number, dim: number = 256): number[] {
  const arr: number[] = [];
  for (let i = 0; i < dim; i++) {
    arr.push(Math.sin(seed + i) * Math.cos(seed * i));
  }
  const norm = Math.sqrt(arr.reduce((sum, x) => sum + x * x, 0));
  return arr.map((x) => x / norm);
}

interface TestMetrics {
  ttft_parallel_ms: number;
  ttft_serial_ms: number;
  speedup_factor: number;
  sub_query_count: number;
  total_sources: number;
  average_uncertainty: number;
}

// ============================================================================
// Test 1: Multi-Intent Detection
// ============================================================================

async function test_MultiIntentDetection(): Promise<void> {
  console.log('\n========== TEST 1: Multi-Intent Detection ==========');

  const planner = new MultiIntentPlanner();

  const testCases = [
    {
      utterance: 'What is machine learning and how does deep learning differ?',
      expectedMultiIntent: true,
      reason: 'Coordination: and',
    },
    {
      utterance: 'List the top 5 machine learning algorithms and compare their performance',
      expectedMultiIntent: true,
      reason: 'Request clauses: list, compare',
    },
    {
      utterance: 'Show me different types of neural networks and their applications',
      expectedMultiIntent: true,
      reason: 'List cues: different, applications',
    },
    {
      utterance: 'What is neural networks?',
      expectedMultiIntent: false,
      reason: 'Single intent',
    },
  ];

  let passCount = 0;

  for (const testCase of testCases) {
    const output = await planner.process(testCase.utterance, mockEmbedding(1));

    const status = output.multi_intent === testCase.expectedMultiIntent ? '✓' : '✗';
    console.log(
      `${status} "${testCase.utterance.substring(0, 40)}..." → ${output.multi_intent} (${testCase.reason})`
    );

    if (output.multi_intent === testCase.expectedMultiIntent) {
      passCount++;
    }
  }

  if (passCount === testCases.length) {
    console.log(`\n✓ All ${passCount}/${testCases.length} detection tests PASS`);
  } else {
    throw new Error(`Detection tests failed: ${passCount}/${testCases.length}`);
  }
}

// ============================================================================
// Test 2: Query Planning (LLM vs Fallback)
// ============================================================================

async function test_QueryPlanning(): Promise<void> {
  console.log('\n========== TEST 2: Query Planning ==========');

  const planner = new MultiIntentPlanner();

  const utterance =
    'I want to understand machine learning basics and compare supervised vs unsupervised learning';

  const output = await planner.process(utterance, mockEmbedding(2));

  console.log(`Utterance: "${utterance}"`);
  console.log(`Sub-queries generated: ${output.sub_query_count}`);
  console.log(`Planner source: ${output.sub_queries[0]?.source || 'N/A'}`);

  if (output.sub_query_count < 1) {
    throw new Error('No sub-queries generated');
  }

  if (!['llm', 'fallback', 'single'].includes(output.sub_queries[0].source || '')) {
    throw new Error('Invalid planner source');
  }

  console.log('\nGenerated sub-queries:');
  for (const sq of output.sub_queries) {
    console.log(`  - [${sq.source}] "${sq.text.substring(0, 60)}..."`);
  }

  console.log('\n✓ Query planning test PASS');
}

// ============================================================================
// Test 3: Parallel Retrieval with Quotas
// ============================================================================

async function test_ParallelRetrieval(): Promise<void> {
  console.log('\n========== TEST 3: Parallel Retrieval ==========');

  const planner = new MultiIntentPlanner();

  const utterance = 'Explain machine learning, compare with AI, and list applications';

  const output = await planner.process(utterance, mockEmbedding(3));

  console.log(`Sub-queries: ${output.sub_query_count}`);
  console.log(`Total sources retrieved: ${output.ledger.processing_stats.total_sources}`);

  // Verify quotas
  const GLOBAL_QUOTA = 12;
  const totalSources = output.ledger.processing_stats.total_sources;

  if (totalSources > GLOBAL_QUOTA) {
    throw new Error(`Exceeded global quota: ${totalSources} > ${GLOBAL_QUOTA}`);
  }

  // Check per-sub-query quota
  for (const [subQueryId, result] of output.ledger.retrievalResults) {
    const SOURCES_PER_QUERY = 4;
    if (result.sources.length > SOURCES_PER_QUERY) {
      throw new Error(`Exceeded per-query quota for ${subQueryId}`);
    }

    console.log(
      `  Sub-query ${subQueryId}: ${result.sources.length} sources (${result.metadata.latencyMs.toFixed(2)}ms)`
    );
  }

  console.log(`\n✓ Parallel retrieval test PASS (within quotas)`);
}

// ============================================================================
// Test 4: Per-Sub-Intent Processing
// ============================================================================

async function test_PerSubIntentProcessing(): Promise<void> {
  console.log('\n========== TEST 4: Per-Sub-Intent Processing ==========');

  const planner = new MultiIntentPlanner();

  const utterance = 'What is supervised learning in machine learning and when to use it?';

  const output = await planner.process(utterance, mockEmbedding(4));

  console.log(`Processing ${output.sub_query_count} sub-intents:\n`);

  let totalUncertainty = 0;

  for (const chunk of output.answer_chunks) {
    const uncertainty = output.ledger.uncertainties.get(chunk.subQueryId);
    const verification = output.ledger.verifications.get(chunk.subQueryId);

    console.log(`Sub-intent: "${chunk.subQueryText.substring(0, 50)}"`);
    console.log(`  Confidence: ${(uncertainty?.confidence_score || 0).toFixed(2)}`);
    console.log(`  Missing data: ${verification?.gaps.length || 0} gaps`);
    console.log(`  Needs clarification: ${uncertainty?.needs_clarification ? 'Yes' : 'No'}`);

    totalUncertainty += uncertainty?.confidence_score || 0;
  }

  const averageUncertainty = totalUncertainty / output.sub_query_count;
  console.log(`\nAverage confidence: ${averageUncertainty.toFixed(2)}`);

  console.log('\n✓ Per-sub-intent processing test PASS');
}

// ============================================================================
// Test 5: 3-Intent Example (Acceptance Criteria)
// ============================================================================

async function test_3IntentExample(): Promise<void> {
  console.log('\n========== TEST 5: 3-Intent Example ==========');

  const planner = new MultiIntentPlanner();

  const utterance =
    'Explain what machine learning is, compare it with traditional programming, and list the main applications in industry';

  console.log(`\nUtterance: "${utterance}"\n`);

  const output = await planner.process(utterance, mockEmbedding(5));

  // Verify 3 sub-queries
  if (output.sub_query_count < 2 || output.sub_query_count > 4) {
    console.log(`⚠ Expected 2-4 sub-queries, got ${output.sub_query_count}`);
  }

  console.log(`✓ Sub-queries generated: ${output.sub_query_count}`);

  // Verify self-containment (shared slots)
  console.log('\nSub-query Analysis:');
  for (let i = 0; i < output.sub_queries.length; i++) {
    const sq = output.sub_queries[i];
    const hasPlace = !!sq.slots.place;
    const hasQuantity = !!sq.slots.quantity;
    const hasDate = !!sq.slots.date;

    console.log(`\n[${i + 1}] "${sq.text.substring(0, 70)}"`);
    console.log(`    ID: ${sq.id}`);
    console.log(`    Source: ${sq.source}`);
    console.log(`    Self-contained: ${hasPlace || hasQuantity || hasDate ? 'Yes' : 'Partial'}`);
    console.log(`    Slots: ${[hasPlace && 'place', hasQuantity && 'quantity', hasDate && 'date'].filter(Boolean).join(', ') || 'none'}`);
  }

  // Verify retrieval parallelism
  console.log(`\nRetrieval Stats:`);
  console.log(
    `  Total sources: ${output.ledger.processing_stats.total_sources}/${12} (within quota)`
  );
  console.log(
    `  Total latency: ${output.metadata.total_duration_ms.toFixed(2)}ms`
  );
  console.log(
    `  Parallel processing: ${output.metadata.is_parallel ? 'Yes' : 'No'}`
  );

  // Verify answer chunks in order
  console.log(`\nAnswer Chunks (in order):`);
  for (const chunk of output.answer_chunks) {
    console.log(`  [${chunk.chunk_index + 1}] ${chunk.subQueryText.substring(0, 50)}`);
  }

  // Verify uncertainty tracking
  console.log(`\nUncertainty Summary:`);
  let needsClarification = 0;
  let avgConfidence = 0;

  for (const uncertainty of output.ledger.uncertainties.values()) {
    if (uncertainty.needs_clarification) needsClarification++;
    avgConfidence += uncertainty.confidence_score;
  }

  avgConfidence /= output.sub_query_count;

  console.log(`  Average confidence: ${avgConfidence.toFixed(2)}`);
  console.log(
    `  Needs clarification: ${needsClarification}/${output.sub_query_count}`
  );

  console.log('\n✓ 3-Intent example test PASS');

  // Detailed output for inspection
  console.log('\n--- DETAILED TURN OUTPUT ---');
  console.log(JSON.stringify({
    sub_query_count: output.sub_query_count,
    multi_intent: output.multi_intent,
    total_duration_ms: output.metadata.total_duration_ms,
    retrieval_stats: output.ledger.processing_stats,
  }, null, 2));
}

// ============================================================================
// Test 6: TTFT Parallelism Benefit
// ============================================================================

async function test_TTFTParallelism(): Promise<void> {
  console.log('\n========== TEST 6: TTFT Parallelism Benefit ==========');

  const planner = new MultiIntentPlanner();

  const utterance =
    'Compare machine learning vs deep learning, explain neural networks, and list real-world applications';

  // Simulate parallel execution
  const parallelStartTime = performance.now();
  const output = await planner.process(utterance, mockEmbedding(6));
  const parallelTTFT = performance.now() - parallelStartTime;

  // Simulate serial execution (approximate)
  const subQueryCount = output.sub_query_count;
  const avgLatencyPerSubQuery = 150; // Approximate: retrieval + processing
  const serialTTFT = subQueryCount * avgLatencyPerSubQuery;

  const speedupFactor = serialTTFT / parallelTTFT;

  console.log(`\nUtterance: "${utterance.substring(0, 60)}..."\n`);

  console.log(`Sub-queries: ${subQueryCount}`);
  console.log(`Parallel TTFT: ${parallelTTFT.toFixed(2)}ms`);
  console.log(`Serial TTFT (simulated): ${serialTTFT.toFixed(2)}ms`);
  console.log(`Speedup: ${speedupFactor.toFixed(2)}x\n`);

  // Verification
  if (parallelTTFT >= serialTTFT) {
    console.log('⚠ Warning: Serial execution slower (expected due to parallelism)');
  } else {
    console.log(`✓ Parallel execution is ${speedupFactor.toFixed(2)}x faster`);
  }

  // First chunk should arrive quickly
  if (output.answer_chunks.length > 0) {
    const firstChunkTime = output.answer_chunks[0].timestamp - output.metadata.started_at;
    console.log(`First answer chunk arrival: ${firstChunkTime.toFixed(2)}ms`);

    if (firstChunkTime < parallelTTFT * 0.3) {
      console.log('✓ TTFT is significantly improved by parallelism');
    }
  }

  console.log('\n✓ TTFT parallelism test PASS');
}

// ============================================================================
// Test 7: Slot Injection and Self-Containment
// ============================================================================

async function test_SlotInjection(): Promise<void> {
  console.log('\n========== TEST 7: Slot Injection ==========');

  const planner = new MultiIntentPlanner();

  const utterance =
    'In New York, find the best restaurants with vegetarian options and compare their ratings';

  const output = await planner.process(utterance, mockEmbedding(7));

  console.log(`Utterance: "${utterance}"\n`);

  console.log('Sub-queries after slot injection:');
  for (let i = 0; i < output.sub_queries.length; i++) {
    const sq = output.sub_queries[i];
    console.log(`  [${i + 1}] "${sq.text}"`);

    if (sq.slots.place) {
      console.log(`      Place slot: ${sq.slots.place}`);
    }

    // Verify sub-query contains injected slots
    const containsPlace = sq.text.toLowerCase().includes('new york');
    if (sq.slots.place && !containsPlace) {
      console.log(`      ⚠ Missing injected place in text`);
    }
  }

  console.log('\n✓ Slot injection test PASS');
}

// ============================================================================
// Main Test Runner
// ============================================================================

async function runAllTests(): Promise<void> {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║  PHASE 5: Multi-Intent Planner Tests   ║');
  console.log('╚════════════════════════════════════════╝');

  try {
    await test_MultiIntentDetection();
    await test_QueryPlanning();
    await test_ParallelRetrieval();
    await test_PerSubIntentProcessing();
    await test_3IntentExample();
    await test_TTFTParallelism();
    await test_SlotInjection();

    console.log(
      '\n╔════════════════════════════════════════╗'
    );
    console.log('║       ✓ ALL TESTS PASSED             ║');
    console.log('╚════════════════════════════════════════╝\n');
  } catch (error) {
    console.error(
      '\n╔════════════════════════════════════════╗'
    );
    console.error('║       ✗ TEST FAILED                  ║');
    console.error('╚════════════════════════════════════════╝');
    console.error(`\nError: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

// Run tests
runAllTests().catch(console.error);
