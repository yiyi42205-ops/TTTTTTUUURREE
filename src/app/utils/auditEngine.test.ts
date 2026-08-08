import { describe, it, expect } from 'vitest';
import {
  aggregateAuditedReviews,
  auditReview,
  mergeStage2Results,
  computeStage2Confidence,
  computeSimilaritySignals,
  computeHotTermSignals,
  computeNearbyLongReviewCounts,
  AuditResult,
} from './auditEngine';
import { Review } from './csvParser';

function review(overrides: Partial<Review> = {}): Review {
  return {
    username: 'user',
    stars: 5,
    time: '2025-01-01',
    text: 'placeholder',
    images: [],
    ...overrides,
  };
}

function audited(review: Review, audit: AuditResult) {
  return { ...review, audit };
}

describe('aggregateAuditedReviews', () => {
  it('all-clean store: uniform weight leaves filteredRating equal to originalRating', () => {
    const clean = (audit: Partial<AuditResult> = {}): AuditResult => ({
      isWashed: false,
      reason: '',
      confidenceScore: 80,
      issueType: null,
      ...audit,
    });

    const reviews = [
      audited(review({ stars: 5 }), clean()),
      audited(review({ stars: 4 }), clean()),
      audited(review({ stars: 5 }), clean()),
    ];

    const result = aggregateAuditedReviews('Clean Shop', reviews);

    expect(result.originalRating).toBe(4.67);
    expect(result.filteredRating).toBe(4.67);
    expect(result.trustScore).toBe(100);
    expect(result.suspiciousReviews).toBe(0);
    expect(result.totalReviews).toBe(3);
  });

  it('mixed-weight store: incentive + no_text washed reviews pull down the filtered rating and trust score', () => {
    const reviews = [
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 100, issueType: 'incentive' }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 1 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 5, text: '' }), { isWashed: true, reason: '', confidenceScore: 65, issueType: 'no_text' }),
    ];

    const result = aggregateAuditedReviews('Mixed Shop', reviews);

    // originalRating = (5+5+1+5)/4 = 4.00
    expect(result.originalRating).toBe(4.00);
    // weightedSum = 5*0 + 5*0.8 + 1*0.8 + 5*0.35 = 6.55; weightTotal = 0+0.8+0.8+0.35 = 1.95
    // filteredRating = 6.55/1.95 = 3.358974... -> 3.36
    // Trust Score is display-only, does NOT modify filteredRating.
    expect(result.filteredRating).toBe(3.36);
    expect(result.trustScore).toBe(0);
    expect(result.suspiciousReviews).toBe(2);
    expect(result.issues.timeAnomaly).toBe(1);
    expect(result.issues.templateText).toBe(0);
    expect(result.issues.vague).toBe(0);
  });

  it('store with no_text reviews: neutral 0.5 weight is applied distinctly from normal clean reviews', () => {
    const reviews = [
      audited(review({ stars: 5, text: '' }), { isWashed: false, reason: '', confidenceScore: 50, issueType: 'no_text' }),
      audited(review({ stars: 3, text: '' }), { isWashed: false, reason: '', confidenceScore: 50, issueType: 'no_text' }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
    ];

    const result = aggregateAuditedReviews('No-text Shop', reviews);

    // originalRating = (5+3+5)/3 = 4.333... -> 4.33
    expect(result.originalRating).toBe(4.33);
    // weightedSum = 5*0.5 + 3*0.5 + 5*0.8 = 8; weightTotal = 0.5+0.5+0.8 = 1.8
    // basicFilteredRating = 8/1.8 = 4.4444...; trustScore stays 100 (no isWashed reviews) -> no penalty
    expect(result.filteredRating).toBe(4.44);
    expect(result.trustScore).toBe(100);
    expect(result.suspiciousReviews).toBe(0);
  });

  it('extreme case: every review judged washed at 100% confidence zeroes out the weight total and falls back to originalRating', () => {
    const reviews = [
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 100, issueType: 'incentive' }),
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 100, issueType: 'incentive' }),
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 100, issueType: 'template' }),
      audited(review({ stars: 1 }), { isWashed: true, reason: '', confidenceScore: 100, issueType: 'incentive' }),
    ];

    const result = aggregateAuditedReviews('All Washed Shop', reviews);

    // weightTotal = 0 for every review -> filteredRating falls back to originalRating
    // Trust Score is display-only and does NOT apply a penalty to filteredRating.
    expect(result.originalRating).toBe(4.00);
    expect(result.filteredRating).toBe(4.00);
    expect(result.trustScore).toBe(0);
    expect(result.suspiciousReviews).toBe(4);
    expect(result.issues.timeAnomaly).toBe(3);
    expect(result.issues.templateText).toBe(1);
  });

  it('empty review list returns a neutral zeroed-out ShopStats', () => {
    const result = aggregateAuditedReviews('Empty Shop', []);

    expect(result.totalReviews).toBe(0);
    expect(result.originalRating).toBe(0);
    expect(result.filteredRating).toBe(0);
    expect(result.trustScore).toBe(100);
    expect(result.suspiciousReviews).toBe(0);
  });

  it('regression: filteredRating equals pure weighted average with no trustPenalty deduction', () => {
    // This test locks in the removal of the trustPenalty double-punishment.
    // filteredRating must equal sum(stars*weight)/sum(weight), with NO
    // additional deduction from Trust Score.
    const reviews = [
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 90, issueType: 'template' }),
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 90, issueType: 'template' }),
      audited(review({ stars: 5 }), { isWashed: true, reason: '', confidenceScore: 90, issueType: 'template' }),
      audited(review({ stars: 4 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 3 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 4 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 2 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
      audited(review({ stars: 4 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
    ];

    const result = aggregateAuditedReviews('Penalty-Free Shop', reviews);

    // 3 washed (weight=0.10 each): 5*0.1*3 = 1.5
    // 7 clean  (weight=0.80 each): (4+3+5+4+2+5+4)*0.8 = 27*0.8 = 21.6
    // weightedSum = 23.1; weightTotal = 0.3+5.6 = 5.9
    // expectedFilteredRating = 23.1 / 5.9 = 3.915254... -> 3.92
    const expectedWeightedAvg = 3.92;
    expect(result.filteredRating).toBe(expectedWeightedAvg);

    // Trust Score should still exist as a display metric (30% washed, 10 total)
    // trustScore = max(0, 100 - (3/10)*100*2) = max(0, 100-60) = 40
    expect(result.trustScore).toBe(40);
  });

  it('store with low_info reviews: neutral 0.55 weight is distinct from no_text (0.5) and clean (0.8)', () => {
    const reviews = [
      audited(review({ stars: 1, text: '好吃' }), { isWashed: false, reason: '', confidenceScore: 55, issueType: 'low_info' }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
    ];

    const result = aggregateAuditedReviews('Low Info Shop', reviews);

    // originalRating = (1+5)/2 = 3.00
    // weightedSum = 1*0.55 + 5*0.8 = 4.55; weightTotal = 0.55+0.8 = 1.35 -> 4.55/1.35 = 3.3703... -> 3.37
    expect(result.originalRating).toBe(3.00);
    expect(result.filteredRating).toBe(3.37);
    expect(result.trustScore).toBe(100);
    expect(result.suspiciousReviews).toBe(0);
  });
});

describe('auditReview - low_info vs escalated washing', () => {
  it('classifies an isolated short generic review as low_info, not washed', () => {
    const result = auditReview(review({ text: '好吃' }));
    expect(result.issueType).toBe('low_info');
    expect(result.isWashed).toBe(false);
    expect(result.confidenceScore).toBe(55);
  });

  it('escalates to washed template when a short generic review co-occurs with a spike period', () => {
    const result = auditReview(review({ text: '讚' }), { isSpikePeriod: true });
    expect(result.issueType).toBe('template');
    expect(result.isWashed).toBe(true);
  });

  it('escalates to washed template when a short generic review has a high similarCount', () => {
    const result = auditReview(review({ text: '推推' }), { similarCount: 2 });
    expect(result.issueType).toBe('template');
    expect(result.isWashed).toBe(true);
  });

  it('does not escalate when similarCount is below the threshold and there is no spike', () => {
    const result = auditReview(review({ text: '棒' }), { similarCount: 1 });
    expect(result.issueType).toBe('low_info');
    expect(result.isWashed).toBe(false);
  });

  it('a review with real content is unaffected by low_info logic regardless of context', () => {
    const result = auditReview(
      review({ text: '今天跟朋友來吃，點了豚骨拉麵麵硬湯濃，叉燒有火烤香氣很讚！不過排隊等了快半小時。' }),
      { isSpikePeriod: true, similarCount: 5 }
    );
    expect(result.issueType).toBe(null);
    expect(result.isWashed).toBe(false);
  });
});

describe('computeSimilaritySignals', () => {
  it('flags near-identical text (2-gram > 75%) as a hard duplicate', () => {
    const reviews = [
      review({ text: '這家拉麵真的超級好吃，湯頭濃郁，叉燒軟嫩，值得推薦給大家。' }),
      review({ text: '這家拉麵真的超級好吃，湯頭濃郁，叉燒軟嫩，值得推薦給大家！' }),
      review({ text: '完全不同的一段話，內容毫無關聯，純粹拿來當作對照組使用。' }),
    ];
    const signals = computeSimilaritySignals(reviews);
    expect(signals[0].isDuplicate).toBe(true);
    expect(signals[1].isDuplicate).toBe(true);
    expect(signals[2].isDuplicate).toBe(false);
  });

  it('reports maxSimilarity/similarCount as a soft 3-gram signal without hard-flagging as duplicate', () => {
    const shared = '招牌黑蒜油豚骨拉麵湯頭濃郁叉燒軟嫩服務親切';
    const reviews = [
      review({ text: shared + '座位舒適很快就吃完了' }),
      review({ text: shared + '還有附贈小菜非常划算' }),
      review({ text: '今天路過隨便晃進來點的東西普普通通沒有特別感覺就這樣離開了' }),
    ];
    const signals = computeSimilaritySignals(reviews);
    expect(signals[0].isDuplicate).toBe(false);
    expect(signals[0].maxSimilarity).toBeGreaterThanOrEqual(0.45);
    expect(signals[0].similarCount).toBe(1);
    expect(signals[2].similarCount).toBe(0);
    expect(signals[2].maxSimilarity).toBe(0);
  });

  it('ignores very short text when computing similarity (avoids noise on trivial strings)', () => {
    const reviews = [
      review({ text: '讚' }),
      review({ text: '讚' }),
    ];
    const signals = computeSimilaritySignals(reviews);
    expect(signals[0].isDuplicate).toBe(false);
    expect(signals[0].similarCount).toBe(0);
  });
});

describe('computeHotTermSignals', () => {
  it('flags a dish name repeated across most 5-star reviews as a hot term', () => {
    const reviews = [
      review({ text: '招牌黑蒜油豚骨拉麵真的很推薦，湯頭濃郁' }),
      review({ text: '朋友介紹來吃黑蒜油豚骨拉麵，確實好吃' }),
      review({ text: '特地來吃黑蒜油豚骨拉麵，果然名不虛傳' }),
      review({ text: '黑蒜油豚骨拉麵是招牌必點，非常推薦' }),
      review({ text: '隨便點了個東西，普普通通沒有特別感覺' }),
    ];
    const signals = computeHotTermSignals(reviews);
    expect(signals[0].hotTermCount).toBeGreaterThan(0);
    expect(signals[0].hotTermMaxRatio).toBeCloseTo(0.8, 1);
    expect(signals[4].hotTermCount).toBe(0);
  });

  it('does not compute hot terms from non-5-star or empty-text reviews', () => {
    const reviews = [
      review({ stars: 4, text: '招牌黑蒜油豚骨拉麵真的很推薦，湯頭濃郁' }),
      review({ stars: 5, text: '' }),
    ];
    const signals = computeHotTermSignals(reviews);
    expect(signals[0].hotTermCount).toBe(0);
    expect(signals[1].hotTermCount).toBe(0);
  });

  it('returns all-zero signals when there are no 5-star reviews with text', () => {
    const reviews = [review({ stars: 3, text: '普通' })];
    const signals = computeHotTermSignals(reviews);
    expect(signals[0]).toEqual({ hotTermCount: 0, hotTermMaxRatio: 0 });
  });
});

describe('mergeStage2Results', () => {
  it('leaves every Stage 1 non-null-issueType verdict completely untouched, even if aiStoreMap has a stray entry for the same username', () => {
    const stage1Audits: Record<string, AuditResult> = {
      incentive: { isWashed: true, reason: 'stage1-incentive', confidenceScore: 100, issueType: 'incentive' },
      template: { isWashed: true, reason: 'stage1-template', confidenceScore: 90, issueType: 'template' },
      no_text: { isWashed: false, reason: 'stage1-no_text', confidenceScore: 50, issueType: 'no_text' },
      low_info: { isWashed: false, reason: 'stage1-low_info', confidenceScore: 55, issueType: 'low_info' },
    };

    const auditedReviews = Object.entries(stage1Audits).map(([username, audit]) =>
      audited(review({ username, text: username }), audit)
    );

    // Simulate the exact bug scenario: Gemini (or a matching bug) somehow has
    // an entry for these usernames even though they were never sent to Stage 2.
    const aiStoreMap: { [username: string]: AuditResult } = {};
    Object.keys(stage1Audits).forEach(username => {
      aiStoreMap[username] = {
        isWashed: !stage1Audits[username].isWashed,
        reason: 'gemini-should-not-apply',
        confidenceScore: 1,
        issueType: 'discrepancy',
        reasoningPath: 'this must never surface',
      };
    });

    const merged = mergeStage2Results(auditedReviews, aiStoreMap);

    merged.forEach(r => {
      expect(r.audit).toEqual(stage1Audits[r.username]);
    });
  });

  it('applies the Gemini result for a genuinely ambiguous (issueType: null) review that was sent to Stage 2', () => {
    const stage1Audit: AuditResult = { isWashed: false, reason: 'stage1-none', confidenceScore: 80, issueType: null };
    const auditedReviews = [audited(review({ username: 'ambiguous_user' }), stage1Audit)];

    const geminiResult: AuditResult = {
      isWashed: true, reason: 'gemini-verdict', confidenceScore: 72, issueType: 'template', reasoningPath: 'CoT',
    };
    const merged = mergeStage2Results(auditedReviews, { ambiguous_user: geminiResult });

    expect(merged[0].audit).toEqual(geminiResult);
  });

  it('leaves an issueType: null review unchanged when Gemini returned no matching result for it', () => {
    const stage1Audit: AuditResult = { isWashed: false, reason: 'stage1-none', confidenceScore: 80, issueType: null };
    const auditedReviews = [audited(review({ username: 'unmatched_user' }), stage1Audit)];

    const merged = mergeStage2Results(auditedReviews, {});

    expect(merged[0].audit).toEqual(stage1Audit);
  });
});

describe('computeNearbyLongReviewCounts', () => {
  const longText = '這是一則超過五十個字的長評論，內容詳細描述了餐點的口感、店內環境、服務態度以及排隊等待的體驗，總之細節非常豐富完整。';

  it('counts other long reviews posted within 30 minutes', () => {
    const reviews = [
      review({ text: longText, time: '2025-01-01T12:00:00Z' }),
      review({ text: longText, time: '2025-01-01T12:15:00Z' }),
      review({ text: longText, time: '2025-01-01T14:00:00Z' }), // 2 hours away — outside the window
      review({ text: '短評', time: '2025-01-01T12:05:00Z' }), // within window but too short to count
    ];
    const counts = computeNearbyLongReviewCounts(reviews);
    expect(counts[0]).toBe(1); // only review[1] is both long and within 30 minutes
    expect(counts[1]).toBe(1);
    expect(counts[2]).toBe(0);
  });

  it('returns 0 for reviews with unparseable or missing timestamps', () => {
    const counts = computeNearbyLongReviewCounts([review({ text: longText, time: '' })]);
    expect(counts[0]).toBe(0);
  });
});

describe('computeStage2Confidence - structural template verdicts stay decoupled from content dimensions', () => {
  // Regression fixture for the real failure case: same store, same opening
  // structure, same signature-dish combo ("有機蝦／黑鑽蜆湯／三品海鮮匯"), same
  // closing line — but scheduled 20 days apart specifically to dodge any
  // time-clustering check. Both reviews read as detailed and well-written
  // (high I/A/D), which is exactly what made the old content-based formula
  // score them at ~2% confidence despite Gemini correctly calling them washed.
  const scheduledTemplateReviews = [
    review({
      username: 'poster1',
      text: '一走進門就被熱情招呼，主廚特製有機蝦鮮甜彈牙，黑鑽蜆湯濃郁鮮美，三品海鮮匯份量十足，CP值爆表，全家都愛，強力推薦！',
      time: '2025-01-01',
    }),
    review({
      username: 'poster2',
      text: '服務態度真的很好，主廚特製有機蝦鮮甜彈牙，黑鑽蜆湯濃郁鮮美，三品海鮮匯份量十足，物超所值，全家都愛，大力推薦！',
      time: '2025-01-21', // 20 days later
    }),
  ];

  it('the two reviews are recognized as structurally similar (soft signal) without being hard duplicates', () => {
    const signals = computeSimilaritySignals(scheduledTemplateReviews);
    expect(signals[0].isDuplicate).toBe(false); // not literal copy-paste
    expect(signals[0].maxSimilarity).toBeGreaterThanOrEqual(0.45);
    expect(signals[0].similarCount).toBe(1);
  });

  it('scores a structural template verdict at >=60% confidence, and weight is significantly below 0.5', () => {
    const signals = computeSimilaritySignals(scheduledTemplateReviews);
    const hotTermSignals = computeHotTermSignals(scheduledTemplateReviews);
    const nearbyLongReviewCounts = computeNearbyLongReviewCounts(scheduledTemplateReviews);

    // Simulates Gemini's response for review[1]: well-written content (high
    // I/A/D) but correctly identified as a structurally-triggered template.
    const geminiItem = {
      isWashed: true,
      issueType: 'template' as const,
      verdictBasis: 'structural' as const,
      incentiveIntensity: 1,
      sentimentAuthenticity: 4,
      descriptionGranularity: 5,
    };

    const confidence = computeStage2Confidence(geminiItem, {
      similarCount: signals[1].similarCount,
      hotTermMaxRatio: hotTermSignals[1].hotTermMaxRatio,
      nearbyLongReviewCount: nearbyLongReviewCounts[1],
    });
    const weight = geminiItem.isWashed ? 1 - confidence / 100 : confidence / 100;

    expect(confidence).toBeGreaterThanOrEqual(60);
    expect(weight).toBeLessThanOrEqual(0.4);
  });

  it('demonstrates the bug the fix corrects: the old content-based (I/A/D) formula would have scored the same verdict at ~2%', () => {
    // Same I/A/D as above, but WITHOUT verdictBasis routing — i.e. the old
    // behavior, reproduced here via the content branch (issueType !== 'template'
    // takes the same agreement^1.5 path regardless of verdictBasis).
    const oldStyleItem = {
      isWashed: true,
      issueType: 'incentive' as const, // forces the content-formula branch for this assertion
      incentiveIntensity: 1,
      sentimentAuthenticity: 4,
      descriptionGranularity: 5,
    };
    const oldConfidence = computeStage2Confidence(oldStyleItem);
    expect(oldConfidence).toBeLessThanOrEqual(5);
  });
});

describe('cross-language fixture: computeHotTermSignals / computeNearbyLongReviewCounts', () => {
  // This exact fixture (same usernames/stars/time/text) is mirrored in
  // evaluate_v2.py's test_evaluate_v2_signal_mirrors.py as CSV-row dicts.
  // Both sides assert the same golden values below — if either
  // implementation (TS or the Python mirror) drifts, its own test fails,
  // catching divergence between the two engines.
  const sharedFixture: Review[] = [
    {
      username: 'u1', stars: 5, time: '2025-01-01T09:00:00',
      text: '今天特地來嚐鮮，招牌黑蒜油豚骨拉麵真的很推薦，湯頭濃郁順口，叉燒軟嫩多汁，非常值得一試，下次還會再來品嚐更多菜色。',
      images: [],
    },
    {
      username: 'u2', stars: 5, time: '2025-01-01T09:15:00',
      text: '朋友介紹來吃黑蒜油豚骨拉麵，確實好吃，湯頭順口不油膩，叉燒也很入味，服務態度親切，整體用餐體驗相當不錯值得推薦。',
      images: [],
    },
    {
      username: 'u3', stars: 5, time: '2025-01-05T10:00:00',
      text: '特地來吃黑蒜油豚骨拉麵，果然名不虛傳，湯頭濃郁香醇，麵條彈牙有嚼勁，是我吃過最好吃的拉麵之一，強力推薦給大家。',
      images: [],
    },
    {
      username: 'u4', stars: 5, time: '2025-01-10T08:00:00',
      text: '隨便點了個東西，普普通通沒有特別感覺，服務也普通，可能不會再來了。',
      images: [],
    },
  ];

  it('computeHotTermSignals matches the golden values (must match the Python mirror)', () => {
    const signals = computeHotTermSignals(sharedFixture);
    expect(signals).toEqual([
      { hotTermCount: 1, hotTermMaxRatio: 0.75 },
      { hotTermCount: 1, hotTermMaxRatio: 0.75 },
      { hotTermCount: 1, hotTermMaxRatio: 0.75 },
      { hotTermCount: 0, hotTermMaxRatio: 0 },
    ]);
  });

  it('computeNearbyLongReviewCounts matches the golden values (must match the Python mirror)', () => {
    const counts = computeNearbyLongReviewCounts(sharedFixture);
    expect(counts).toEqual([1, 1, 0, 0]);
  });
});
