// Node name: Vision Results Merger
// Position: after all Vision Analyst HTTP Request calls are merged
// Input: multiple items — each item.json is a VisionAnalysisResult (parsed)
// Output: single object with plain-text summary for Hook Strategist + structured ad_summaries

const analyses = $input.all().filter(a => !a.json.error && a.json.analysis);

const layoutCounts = {};
const formulaCounts = {};
const offerTypeCounts = {};
const toneCounts = {};
const spendTierCounts = {};
const trustElementCounts = {};
let faceCount = 0;
let comparisonCount = 0;
const adSummaries = [];

for (const item of analyses) {
  const a = item.json.analysis;
  const vs = a.visual_structure;
  const ca = a.copy_analysis;
  const oah = a.offer_and_hook;
  const bs = a.brand_signals;
  const cq = a.creative_quality;

  layoutCounts[vs.layout_type] = (layoutCounts[vs.layout_type] || 0) + 1;
  if (ca.headline_formula) formulaCounts[ca.headline_formula] = (formulaCounts[ca.headline_formula] || 0) + 1;
  if (oah.offer_type) offerTypeCounts[oah.offer_type] = (offerTypeCounts[oah.offer_type] || 0) + 1;
  if (ca.tone) toneCounts[ca.tone] = (toneCounts[ca.tone] || 0) + 1;
  if (cq.estimated_ad_spend_tier) spendTierCounts[cq.estimated_ad_spend_tier] = (spendTierCounts[cq.estimated_ad_spend_tier] || 0) + 1;
  if (vs.has_human_face) faceCount++;
  if (bs.competitor_comparison) comparisonCount++;
  for (const te of bs.trust_elements || []) {
    trustElementCounts[te] = (trustElementCounts[te] || 0) + 1;
  }

  adSummaries.push({
    competitor: item.json.competitor_name || 'Unknown',
    layout: vs.layout_type,
    headline: ca.headline || '(no headline)',
    offer: oah.offer_type,
    hook_formula: ca.headline_formula,
    spend_tier: cq.estimated_ad_spend_tier,
    primary_hook: oah.primary_hook,
    tone: ca.tone,
    brand_tier: bs.brand_tier_signal,
    trust_elements: bs.trust_elements || []
  });
}

const top = (obj, n = 3) =>
  Object.entries(obj)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([name, count]) => `${name} (${count}x)`)
    .join(', ');

const total = analyses.length;

// Plain-text summary consumed by Hook Strategist system prompt
const summary = `COMPETITOR AD ANALYSIS — ${total} ads

VISUAL PATTERNS:
- Dominant layouts: ${top(layoutCounts)}
- Ads with human faces: ${faceCount}/${total}
- Ads running competitor comparisons: ${comparisonCount}/${total}

COPY PATTERNS:
- Dominant headline formulas: ${top(formulaCounts)}
- Dominant tones: ${top(toneCounts)}
- Common offer types: ${top(offerTypeCounts)}
- Trust elements present: ${top(trustElementCounts)}

SPEND TIER DISTRIBUTION:
${Object.entries(spendTierCounts).map(([k, v]) => `- ${k}: ${v} ads`).join('\n')}

PER-AD SUMMARY (use for counter-positioning opportunities):
${adSummaries.map((ad, i) =>
  `[Ad ${i + 1}] ${ad.competitor} | Layout: ${ad.layout} | Formula: ${ad.hook_formula} | Tone: ${ad.tone} | Offer: ${ad.offer} | Spend: ${ad.spend_tier}
  Headline: "${ad.headline}"
  Hook: ${ad.primary_hook}`
).join('\n\n')}`;

return [{
  json: {
    vision_analysis_summary: summary,
    ad_summaries: adSummaries,
    total_ads_analysed: total,
    pattern_counts: {
      layouts: layoutCounts,
      headline_formulas: formulaCounts,
      offer_types: offerTypeCounts,
      tones: toneCounts,
      spend_tiers: spendTierCounts,
      trust_elements: trustElementCounts
    }
  }
}];
