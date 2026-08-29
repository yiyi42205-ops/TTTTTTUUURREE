import { describe, it, expect } from 'vitest';
import {
  aggregateAuditedReviews,
  mergeStage2Results,
  computeStage2Confidence,
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

    expect(result.originalRating).toBe(4.00);
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

    expect(result.originalRating).toBe(4.33);
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

    const expectedWeightedAvg = 3.92;
    expect(result.filteredRating).toBe(expectedWeightedAvg);
    expect(result.trustScore).toBe(40);
  });

  it('store with low_info reviews: neutral 0.55 weight is distinct from no_text (0.5) and clean (0.8)', () => {
    const reviews = [
      audited(review({ stars: 1, text: '好吃' }), { isWashed: false, reason: '', confidenceScore: 55, issueType: 'low_info' }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
    ];

    const result = aggregateAuditedReviews('Low Info Shop', reviews);

    expect(result.originalRating).toBe(3.00);
    expect(result.filteredRating).toBe(3.37);
    expect(result.trustScore).toBe(100);
    expect(result.suspiciousReviews).toBe(0);
  });

  it('unaudited reviews use fixed 0.65 weight, not the confidence-based formula', () => {
    const reviews = [
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: 'unaudited' }),
      audited(review({ stars: 3 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: 'unaudited' }),
      audited(review({ stars: 5 }), { isWashed: false, reason: '', confidenceScore: 80, issueType: null }),
    ];

    const result = aggregateAuditedReviews('Unaudited Shop', reviews);

    // unaudited weight = 0.65 (fixed), clean weight = 0.8
    // weighted sum = 5*0.65 + 3*0.65 + 5*0.8 = 3.25 + 1.95 + 4.0 = 9.2
    // weight total = 0.65 + 0.65 + 0.8 = 2.1
    // filtered = 9.2 / 2.1 ≈ 4.38
    expect(result.filteredRating).toBe(4.38);
    expect(result.suspiciousReviews).toBe(0);
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

  it('marks an issueType: null review as unaudited when Gemini returned no matching result for it', () => {
    const stage1Audit: AuditResult = { isWashed: false, reason: 'stage1-none', confidenceScore: 80, issueType: null };
    const auditedReviews = [audited(review({ username: 'unmatched_user' }), stage1Audit)];

    const merged = mergeStage2Results(auditedReviews, {});

    expect(merged[0].audit.issueType).toBe('unaudited');
    expect(merged[0].audit.isWashed).toBe(false);
  });
});

describe('computeStage2Confidence - structural template verdicts stay decoupled from content dimensions', () => {
  it('scores a structural template verdict at >=60% confidence, and weight is significantly below 0.5', () => {
    // Simulates Gemini's response: well-written content (high I/A/D) but
    // correctly identified as a structurally-triggered template.
    const geminiItem = {
      isWashed: true,
      issueType: 'template' as const,
      verdictBasis: 'structural' as const,
      incentiveIntensity: 1,
      sentimentAuthenticity: 4,
      descriptionGranularity: 5,
    };

    // Signal values from the backend for the structurally similar review pair
    const confidence = computeStage2Confidence(geminiItem, {
      similarCount: 1,
      hotTermMaxRatio: 0.75,
      nearbyLongReviewCount: 0,
    });
    const weight = geminiItem.isWashed ? 1 - confidence / 100 : confidence / 100;

    expect(confidence).toBeGreaterThanOrEqual(60);
    expect(weight).toBeLessThanOrEqual(0.4);
  });

  it('demonstrates the bug the fix corrects: the old content-based (I/A/D) formula would have scored the same verdict at ~2%', () => {
    const oldStyleItem = {
      isWashed: true,
      issueType: 'incentive' as const, // forces the content-formula branch
      incentiveIntensity: 1,
      sentimentAuthenticity: 4,
      descriptionGranularity: 5,
    };
    const oldConfidence = computeStage2Confidence(oldStyleItem);
    expect(oldConfidence).toBeLessThanOrEqual(5);
  });
});
