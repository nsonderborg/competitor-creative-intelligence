// Node name: Output Formatter
// Position: final node before Webhook Response / Postgres INSERT
// Reads from upstream nodes by name — update names below if you rename nodes in n8n
//
// Expected upstream node names (rename to match yours):
//   "Input Validator"       — has run_id, brand_name, started_at
//   "Vision Results Merger" — has total_ads_analysed
//   "Review Aggregator"     — has total_reviews_processed
//   "Hook Strategist"       — has hooks[], strategy_brief, input_tokens, output_tokens
//   "Report Writer"         — has brand_report (markdown string), input_tokens, output_tokens
//   "Vision Analyst"        — all items, each has input_tokens, output_tokens, cache_* tokens
//   "Review Miner"          — all items, each has input_tokens, output_tokens, cache_* tokens

// --- Pricing constants (per million tokens, May 2026) ---
const PRICE = {
  sonnet: { input: 3.00, output: 15.00, cacheWrite: 3.75, cacheRead: 0.30 },
  haiku:  { input: 0.80, output:  4.00, cacheWrite: 1.00, cacheRead: 0.08 }
};

function cost(inputTokens, outputTokens, cacheWrite, cacheRead, model) {
  const p = PRICE[model];
  const regularInput = Math.max(0, inputTokens - (cacheWrite || 0) - (cacheRead || 0));
  return (
    regularInput     * p.input      / 1_000_000 +
    outputTokens     * p.output     / 1_000_000 +
    (cacheWrite || 0) * p.cacheWrite / 1_000_000 +
    (cacheRead  || 0) * p.cacheRead  / 1_000_000
  );
}

function sumTokens(items) {
  return items.reduce((acc, item) => ({
    input:      acc.input      + (item.json.input_tokens  || 0),
    output:     acc.output     + (item.json.output_tokens || 0),
    cacheWrite: acc.cacheWrite + (item.json.cache_creation_input_tokens || 0),
    cacheRead:  acc.cacheRead  + (item.json.cache_read_input_tokens     || 0)
  }), { input: 0, output: 0, cacheWrite: 0, cacheRead: 0 });
}

// --- Gather upstream data ---
const inputNode    = $('Input Validator').first().json;
const visionMerger = $('Vision Results Merger').first().json;
const reviewAgg    = $('Review Aggregator').first().json;
const hooksNode    = $('Hook Strategist').first().json;
const reportNode   = $('Report Writer').first().json;

const visionItems = $('Vision Analyst').all();
const reviewItems = $('Review Miner').all();

const vt = sumTokens(visionItems);
const rt = sumTokens(reviewItems);

const visionCost = cost(vt.input, vt.output, vt.cacheWrite, vt.cacheRead, 'sonnet');
const reviewCost = cost(rt.input, rt.output, rt.cacheWrite, rt.cacheRead, 'haiku');
const hooksCost  = cost(hooksNode.input_tokens || 0, hooksNode.output_tokens || 0, 0, 0, 'sonnet');
const reportCost = cost(reportNode.input_tokens || 0, reportNode.output_tokens || 0, 0, 0, 'sonnet');
const totalCost  = visionCost + reviewCost + hooksCost + reportCost;

// --- Assemble output ---
const completedAt = new Date().toISOString();
const startedAt   = inputNode.started_at || completedAt;
const durationSeconds = Math.round(
  (new Date(completedAt) - new Date(startedAt)) / 1000
);

const sortedHooks = [...(hooksNode.hooks || [])].sort(
  (a, b) => b.confidence_score - a.confidence_score
);

// Extract markdown — Report Writer returns raw Claude response; parse content field if needed
const brandReport = typeof reportNode.brand_report === 'string'
  ? reportNode.brand_report
  : (reportNode.content || '');

return [{
  json: {
    run_id:           inputNode.run_id,
    brand_name:       inputNode.brand_name,
    started_at:       startedAt,
    completed_at:     completedAt,
    duration_seconds: durationSeconds,
    hooks:            sortedHooks,
    brand_report:     brandReport,
    strategy_brief:   hooksNode.strategy_brief || null,
    run_stats: {
      ads_analysed:        visionMerger.total_ads_analysed || visionItems.length,
      reviews_processed:   reviewAgg.total_reviews_processed || 0,
      hooks_generated:     sortedHooks.length,
      total_input_tokens:  vt.input + rt.input + (hooksNode.input_tokens || 0) + (reportNode.input_tokens || 0),
      total_output_tokens: vt.output + rt.output + (hooksNode.output_tokens || 0) + (reportNode.output_tokens || 0),
      estimated_cost_usd:  Math.round(totalCost * 10000) / 10000,
      sonnet_calls:        visionItems.length + 2,  // vision + hook strategist + report writer
      haiku_calls:         reviewItems.length
    }
  }
}];
