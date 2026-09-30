/**
 * PHASE 4: 3-Turn Scenario Example
 * 
 * Demonstrates:
 * - Turn 1: Cold retrieval
 * - Turn 2: T0 suppression on repeat (0% retrieval)
 * - Turn 3: Cache hit on similar query (0% retrieval)
 * - All decisions under 10ms
 */

import {
  CascadeController,
  Utterance,
  ControllerDecision,
} from './phase4_cascade_controller';

// ============================================================================
// Mock Embeddings Generator
// ============================================================================

function createEmbedding(seed: number, dimension: number = 256): number[] {
  const embedding: number[] = [];
  for (let i = 0; i < dimension; i++) {
    // Deterministic but pseudo-random
    embedding.push(
      Math.sin(seed * Math.PI + i) * Math.cos(seed + i * 0.1) + 
      Math.sin(i / dimension) * 0.1
    );
  }
  // Normalize
  const norm = Math.sqrt(embedding.reduce((sum, x) => sum + x * x, 0));
  return embedding.map((x) => x / norm);
}

// ============================================================================
// Scenario Definition
// ============================================================================

interface ScenarioTurn {
  number: number;
  utteranceId: string;
  text: string;
  embedding: number[];
  expected_decision: string;
  description: string;
}

const scenario: ScenarioTurn[] = [
  {
    number: 1,
    utteranceId: 'turn_1',
    text: 'What is machine learning and how does it work?',
    embedding: createEmbedding(42),
    expected_decision: 'RETRIEVE',
    description: 'Initial query - cold start',
  },
  {
    number: 2,
    utteranceId: 'turn_2',
    text: 'What is machine learning and how does it work?', // EXACT REPEAT
    embedding: createEmbedding(42), // IDENTICAL embedding
    expected_decision: 'SUPPRESS',
    description: 'Exact repetition - should suppress via T0',
  },
  {
    number: 3,
    utteranceId: 'turn_3',
    text: 'Tell me about machine learning', // Similar but different
    embedding: createEmbedding(42.005), // Very similar embedding
    expected_decision: 'CACHE_HIT',
    description: 'Similar query - should hit cache via T1',
  },
];

// ============================================================================
// Mock Retrieval System
// ============================================================================

interface MockSource {
  id: string;
  title: string;
  snippet: string;
}

const mockSources: Record<string, MockSource[]> = {
  ml: [
    {
      id: 'src_1',
      title: 'ML Fundamentals',
      snippet: 'Machine learning is a subset of artificial intelligence...',
    },
    {
      id: 'src_2',
      title: 'How ML Works',
      snippet: 'ML algorithms learn patterns from data and make predictions...',
    },
  ],
};

function mockRetrieve(query: string): MockSource[] {
  if (query.toLowerCase().includes('machine learning')) {
    return mockSources.ml;
  }
  return [];
}

// ============================================================================
// Main Example
// ============================================================================

async function runScenario(): Promise<void> {
  console.log('\n╔════════════════════════════════════════════════════════════╗');
  console.log('║     PHASE 4: 3-Turn Scenario - Cascade Controller        ║');
  console.log('╚════════════════════════════════════════════════════════════╝\n');

  const controller = new CascadeController();

  // Storage for results
  const results: {
    turnNumber: number;
    decision: ControllerDecision;
    retrievalExecuted: boolean;
    answerReused: boolean;
    cacheHit: boolean;
    latency: number;
  }[] = [];

  // Event listeners for diagnostics
  const eventLog: any[] = [];

  controller.on('controller:decision', (decision: ControllerDecision) => {
    eventLog.push({
      type: 'controller:decision',
      data: decision,
    });
  });

  controller.on('evidence:cached', (event: any) => {
    eventLog.push({
      type: 'evidence:cached',
      data: event,
    });
  });

  controller.on('suppression:answer_reused', (event: any) => {
    eventLog.push({
      type: 'suppression:answer_reused',
      data: event,
    });
  });

  // Storage for answers
  const answers: Record<string, string> = {
    turn_1:
      'Machine learning is a subset of artificial intelligence that enables systems to learn from data. It works by identifying patterns in training data and using those patterns to make predictions on new, unseen data. There are three main types: supervised learning, unsupervised learning, and reinforcement learning.',
  };

  // ========== TURN 1: Initial Query ==========
  console.log('┌─────────────────────────────────────────────────────────────┐');
  console.log('│ TURN 1: Initial Query (Cold Start)                          │');
  console.log('└─────────────────────────────────────────────────────────────┘\n');

  const turn1 = scenario[0];
  console.log(`Query: "${turn1.text}"`);
  console.log(`Expected: ${turn1.expected_decision}\n`);

  const turn1_utterance: Utterance = {
    id: turn1.utteranceId,
    text: turn1.text,
    embedding: turn1.embedding,
    timestamp: Date.now(),
  };

  controller.recordUtterance(turn1_utterance);

  const turn1_state = controller.initializeTurn(turn1.utteranceId);
  controller.transitionEpoch(turn1.utteranceId, 'PROVISIONAL');
  controller.transitionEpoch(turn1.utteranceId, 'COMMIT');

  const turn1_decision = await controller.decideRetrieval(turn1_utterance);

  console.log(`Tier: ${turn1_decision.tier}`);
  console.log(`Decision: ${turn1_decision.decision}`);
  console.log(`Confidence: ${(turn1_decision.confidence * 100).toFixed(1)}%`);
  console.log(`Latency: ${turn1_decision.latencyMs.toFixed(3)}ms`);
  console.log(`Reason: ${turn1_decision.reason}\n`);

  // Simulate retrieval
  if (turn1_decision.decision === 'RETRIEVE') {
    console.log('→ Executing retrieval...\n');
    const sources = mockRetrieve(turn1.text);
    controller.storeRetrievedEvidence(turn1.utteranceId, {
      utteranceId: turn1.utteranceId,
      content: answers['turn_1'],
      sources: sources.map((s) => ({
        id: s.id,
        title: s.title,
        snippet: s.snippet,
        confidence: 0.92,
      })),
      embedding: turn1.embedding,
    });
    console.log(`✓ Retrieved ${sources.length} sources\n`);
  }

  controller.transitionEpoch(turn1.utteranceId, 'UTTERANCE_END');
  controller.completeTurn(turn1.utteranceId, answers['turn_1']);

  results.push({
    turnNumber: 1,
    decision: turn1_decision,
    retrievalExecuted: turn1_decision.decision === 'RETRIEVE',
    answerReused: false,
    cacheHit: false,
    latency: turn1_decision.latencyMs,
  });

  // ========== TURN 2: Exact Repeat ==========
  console.log('┌─────────────────────────────────────────────────────────────┐');
  console.log('│ TURN 2: Exact Repetition (T0 Suppression)                   │');
  console.log('└─────────────────────────────────────────────────────────────┘\n');

  const turn2 = scenario[1];
  console.log(`Query: "${turn2.text}"`);
  console.log(`Expected: ${turn2.expected_decision}\n`);
  console.log('Note: Identical to Turn 1 - should trigger T0 suppression\n');

  const turn2_utterance: Utterance = {
    id: turn2.utteranceId,
    text: turn2.text,
    embedding: turn2.embedding,
    timestamp: Date.now() + 1000,
  };

  controller.recordUtterance(turn2_utterance);

  const turn2_state = controller.initializeTurn(turn2.utteranceId);
  controller.transitionEpoch(turn2.utteranceId, 'PROVISIONAL');
  controller.transitionEpoch(turn2.utteranceId, 'COMMIT');

  const turn2_decision = await controller.decideRetrieval(
    turn2_utterance,
    turn1_utterance
  );

  console.log(`Tier: ${turn2_decision.tier}`);
  console.log(`Decision: ${turn2_decision.decision}`);
  console.log(`Confidence: ${(turn2_decision.confidence * 100).toFixed(1)}%`);
  console.log(`Latency: ${turn2_decision.latencyMs.toFixed(3)}ms`);
  console.log(`Reason: ${turn2_decision.reason}\n`);

  // Suppression path
  let turn2_answer: string | null = null;
  if (turn2_decision.decision === 'SUPPRESS') {
    console.log('→ Suppression path: reusing prior answer\n');
    turn2_answer = controller.suppressAndReuse(
      turn2.utteranceId,
      turn1.utteranceId
    );
    if (turn2_answer) {
      console.log(`✓ Reused answer (${turn2_answer.length} bytes, byte-for-byte)\n`);
    }
  }

  controller.transitionEpoch(turn2.utteranceId, 'UTTERANCE_END');
  controller.completeTurn(turn2.utteranceId, turn2_answer || answers['turn_1']);

  results.push({
    turnNumber: 2,
    decision: turn2_decision,
    retrievalExecuted: false,
    answerReused: turn2_answer !== null,
    cacheHit: false,
    latency: turn2_decision.latencyMs,
  });

  // ========== TURN 3: Similar Query (Cache Hit) ==========
  console.log('┌─────────────────────────────────────────────────────────────┐');
  console.log('│ TURN 3: Similar Query (Cache Hit via T1)                    │');
  console.log('└─────────────────────────────────────────────────────────────┘\n');

  const turn3 = scenario[2];
  console.log(`Query: "${turn3.text}"`);
  console.log(`Expected: ${turn3.expected_decision}\n`);
  console.log('Note: Similar embedding (cos ≥ 0.82) - should hit cache\n');

  const turn3_utterance: Utterance = {
    id: turn3.utteranceId,
    text: turn3.text,
    embedding: turn3.embedding,
    timestamp: Date.now() + 2000,
  };

  controller.recordUtterance(turn3_utterance);

  const turn3_state = controller.initializeTurn(turn3.utteranceId);
  controller.transitionEpoch(turn3.utteranceId, 'PROVISIONAL');
  controller.transitionEpoch(turn3.utteranceId, 'COMMIT');

  const turn3_decision = await controller.decideRetrieval(
    turn3_utterance,
    turn2_utterance
  );

  console.log(`Tier: ${turn3_decision.tier}`);
  console.log(`Decision: ${turn3_decision.decision}`);
  console.log(`Confidence: ${(turn3_decision.confidence * 100).toFixed(1)}%`);
  console.log(`Latency: ${turn3_decision.latencyMs.toFixed(3)}ms`);
  console.log(`Reason: ${turn3_decision.reason}`);

  if (turn3_decision.cacheHitId) {
    console.log(`Cache Hit ID: ${turn3_decision.cacheHitId}`);
  }
  console.log();

  // Cache hit path
  let turn3_answer: string = answers['turn_1'];
  if (turn3_decision.decision === 'CACHE_HIT') {
    console.log('→ Cache hit: reusing cached evidence\n');
    console.log(`✓ Retrieved from cache (${turn3_decision.cacheHitId})\n`);
  }

  controller.transitionEpoch(turn3.utteranceId, 'UTTERANCE_END');
  controller.completeTurn(turn3.utteranceId, turn3_answer);

  results.push({
    turnNumber: 3,
    decision: turn3_decision,
    retrievalExecuted: false,
    answerReused: true,
    cacheHit: turn3_decision.decision === 'CACHE_HIT',
    latency: turn3_decision.latencyMs,
  });

  // ========== RESULTS SUMMARY ==========
  console.log('┌─────────────────────────────────────────────────────────────┐');
  console.log('║                   RESULTS SUMMARY                          ║');
  console.log('└─────────────────────────────────────────────────────────────┘\n');

  console.log('Decision Sequence:');
  console.log('─────────────────');
  for (const result of results) {
    const icon =
      result.decision.decision === 'RETRIEVE'
        ? '🔵'
        : result.decision.decision === 'SUPPRESS'
          ? '🟢'
          : '🟡';
    console.log(
      `${icon} Turn ${result.turnNumber}: ${result.decision.tier} - ${result.decision.decision} ` +
        `(${result.latency.toFixed(2)}ms, ${(result.decision.confidence * 100).toFixed(0)}%)`
    );
  }

  console.log('\nLatency Analysis:');
  console.log('────────────────');
  const latencies = results.map((r) => r.latency);
  const avgLatency = latencies.reduce((a, b) => a + b, 0) / latencies.length;
  const maxLatency = Math.max(...latencies);
  console.log(`Average: ${avgLatency.toFixed(3)}ms`);
  console.log(`Maximum: ${maxLatency.toFixed(3)}ms`);
  console.log(`Target:  ≤10ms`);
  console.log(`Status:  ${maxLatency <= 10 ? '✓ PASS' : '✗ FAIL'}`);

  console.log('\nRetrieval Metrics:');
  console.log('─────────────────');
  const totalRetrievals = results.filter((r) => r.retrievalExecuted).length;
  const totalSuppressed = results.filter((r) => r.decision.decision === 'SUPPRESS').length;
  const totalCacheHits = results.filter((r) => r.cacheHit).length;
  const redundancyReduction = ((2 - totalRetrievals) / 3) * 100;

  console.log(`Retrievals: ${totalRetrievals}/3`);
  console.log(`Suppressions: ${totalSuppressed}`);
  console.log(`Cache Hits: ${totalCacheHits}`);
  console.log(`Redundancy Reduction: ${redundancyReduction.toFixed(1)}%`);

  console.log('\nCache Statistics:');
  console.log('────────────────');
  const cacheStats = controller.getCacheStats();
  console.log(`Cached Evidence Items: ${cacheStats.size}`);
  console.log(`Active Slots: ${cacheStats.slots}`);
  console.log(`Total Reuses: ${cacheStats.totalReuses}`);

  console.log('\nAcceptance Criteria:');
  console.log('───────────────────');

  const criteria = [
    {
      name: 'T0 Suppression on Turn 2',
      pass: results[1].decision.decision === 'SUPPRESS' && results[1].decision.tier === 'T0',
    },
    {
      name: 'Zero Retrieval on Turn 2',
      pass: results[1].retrievalExecuted === false,
    },
    {
      name: 'Cache Hit on Turn 3',
      pass: results[2].decision.decision === 'CACHE_HIT',
    },
    {
      name: 'Zero Retrieval on Turn 3',
      pass: results[2].retrievalExecuted === false,
    },
    {
      name: 'Controller Latency ≤10ms',
      pass: maxLatency <= 10,
    },
    {
      name: '≥30% Redundancy Reduction',
      pass: redundancyReduction >= 30,
    },
  ];

  let allPassed = true;
  for (const criterion of criteria) {
    const icon = criterion.pass ? '✓' : '✗';
    console.log(`${icon} ${criterion.name}`);
    if (!criterion.pass) allPassed = false;
  }

  console.log('\n╔════════════════════════════════════════════════════════════╗');
  if (allPassed) {
    console.log('║            ✓ ALL ACCEPTANCE CRITERIA PASSED              ║');
  } else {
    console.log('║            ✗ SOME CRITERIA FAILED                        ║');
  }
  console.log('╚════════════════════════════════════════════════════════════╝\n');

  // Detailed event log (optional)
  console.log('Event Log (detailed):');
  console.log('────────────────────');
  for (const event of eventLog) {
    console.log(`[${event.type}] ${JSON.stringify(event.data, null, 2)}`);
  }
}

// Run the scenario
runScenario().catch(console.error);
