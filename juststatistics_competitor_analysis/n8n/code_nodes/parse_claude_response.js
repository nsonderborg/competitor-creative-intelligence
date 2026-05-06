// Node name: Parse Claude Response
// Position: immediately after EVERY Claude API HTTP Request node
// Handles: JSON parsing, token count extraction, error surfacing
//
// Usage: one instance after each of these nodes:
//   - Vision Analyst HTTP Request
//   - Review Miner HTTP Request
//   - Hook Strategist HTTP Request
//   - Report Writer HTTP Request
//
// For Vision Analyst / Review Miner / Hook Strategist: sets outputMode = 'json'
// For Report Writer: sets outputMode = 'markdown' to skip JSON.parse

// Set this per-instance to 'json' or 'markdown'
const OUTPUT_MODE = 'json';  // change to 'markdown' for Report Writer instance

const response = $input.first().json;

// Surface API errors immediately — don't pass empty data downstream
if (response.error) {
  throw new Error(`Claude API error: ${JSON.stringify(response.error)}`);
}

if (!response.content || !response.content[0]) {
  throw new Error('Claude API returned empty content');
}

const rawText = response.content[0].text;
const usage   = response.usage || {};

let parsed;
if (OUTPUT_MODE === 'json') {
  try {
    // Strip markdown code fences if Claude wraps output despite instructions
    const cleaned = rawText.replace(/^```json\s*/i, '').replace(/\s*```$/, '').trim();
    parsed = JSON.parse(cleaned);
  } catch (e) {
    throw new Error(`Failed to parse Claude JSON output: ${e.message}\n\nRaw output (first 500 chars):\n${rawText.slice(0, 500)}`);
  }
} else {
  parsed = { brand_report: rawText };
}

return [{
  json: {
    ...parsed,
    // Token counts — passed through to Output Formatter for cost calculation
    input_tokens:                   usage.input_tokens                   || 0,
    output_tokens:                  usage.output_tokens                  || 0,
    cache_creation_input_tokens:    usage.cache_creation_input_tokens    || 0,
    cache_read_input_tokens:        usage.cache_read_input_tokens        || 0,
    model_used:                     response.model                       || ''
  }
}];
