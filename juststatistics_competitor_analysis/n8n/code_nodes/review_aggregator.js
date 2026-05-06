// Node name: Review Aggregator
// Position: after all Review Miner HTTP Request calls are merged
// Input: multiple items — each item.json is a ReviewBatchResult
// Output: single AggregatedReviewIntelligence object

const batches = $input.all();

const allReviews = [];
const painCounts = {};
const desireCounts = {};
const allHookCandidates = [];
let totalSentiment = 0;
let totalReviews = 0;
let bestInsight = '';

for (const batch of batches) {
  const result = batch.json.result;
  if (!result || batch.json.error) continue;

  for (const review of result.reviews || []) {
    allReviews.push(review);
    totalSentiment += review.sentiment.score;
    totalReviews++;

    const pain = review.pain_point.category;
    if (pain !== 'no_pain_point') {
      painCounts[pain] = (painCounts[pain] || 0) + 1;
    }

    const desire = review.desire.category;
    if (desire !== 'no_desire_expressed') {
      desireCounts[desire] = (desireCounts[desire] || 0) + 1;
    }

    if (review.hook_potential.usable_as_hook && review.hook_potential.hook_candidate) {
      allHookCandidates.push(review.hook_potential.hook_candidate);
    }
  }

  if (result.aggregate?.brand_summary_insight) {
    bestInsight = result.aggregate.brand_summary_insight;
  }
}

const sortByCount = (obj) =>
  Object.entries(obj)
    .sort((a, b) => b[1] - a[1])
    .map(([category, count]) => ({
      category,
      count,
      percentage: totalReviews > 0
        ? Math.round((count / totalReviews) * 1000) / 10
        : 0,
      best_verbatim: allReviews.find(r =>
        (r.pain_point?.category === category && r.pain_point?.pain_verbatim) ||
        (r.desire?.category === category && r.desire?.desire_verbatim)
      )?.pain_point?.pain_verbatim
        || allReviews.find(r => r.desire?.category === category)?.desire?.desire_verbatim
        || null
    }));

const uniqueHooks = [...new Set(allHookCandidates)].slice(0, 10);

return [{
  json: {
    total_reviews_processed: totalReviews,
    overall_average_sentiment: totalReviews > 0
      ? Math.round((totalSentiment / totalReviews) * 100) / 100
      : 0,
    top_pain_points: sortByCount(painCounts).slice(0, 5),
    top_desires: sortByCount(desireCounts).slice(0, 5),
    top_hook_candidates: uniqueHooks,
    brand_summary_insight: bestInsight
  }
}];
