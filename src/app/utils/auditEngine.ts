import { Review } from './csvParser';

export interface AuditResult {
  isWashed: boolean;
  reason: string;
  confidenceScore: number;
  issueType: 'incentive' | 'template' | 'discrepancy' | 'no_text' | 'low_info' | 'unaudited' | null;
  reasoningPath?: string;
  incentiveIntensity?: number;
  sentimentAuthenticity?: number;
  descriptionGranularity?: number;
  verdictBasis?: 'content' | 'structural';
}

export interface SimilaritySignal {
  isDuplicate: boolean;
  maxSimilarity: number;
  similarCount: number;
}

export interface HotTermSignal {
  hotTermCount: number;
  hotTermMaxRatio: number;
}

export interface ShopStats {
  storeName: string;
  originalRating: number;
  filteredRating: number;
  trustScore: number;
  totalReviews: number;
  googleReviewsCount?: number;
  reviewAvgRating?: number;
  suspiciousReviews: number;
  issues: {
    timeAnomaly: number;
    templateText: number;
    vague: number;
    noText: number;
    lowInfo: number;
    unaudited: number;
  };
  ratingDistribution: {
    original: { [key: number]: number };
    filtered: { [key: number]: number };
  };
  auditedReviews: (Review & { audit: AuditResult })[];
}

export interface Stage2Item {
  isWashed: boolean;
  issueType?: string | null;
  verdictBasis?: 'content' | 'structural';
  incentiveIntensity?: number;
  sentimentAuthenticity?: number;
  descriptionGranularity?: number;
}

export interface Stage2SignalContext {
  similarCount?: number;
  hotTermMaxRatio?: number;
  nearbyLongReviewCount?: number;
}

// Caps used to normalize the structural signals into a 0-1 composite before
// mapping to the confidence range — these are "how much is a lot" judgment
// calls, not measured constants.
const STRUCTURAL_SIMILAR_COUNT_CAP = 5;
const STRUCTURAL_NEARBY_LONG_REVIEW_CAP = 5;
const STRUCTURAL_CONFIDENCE_MIN = 60;
const STRUCTURAL_CONFIDENCE_MAX = 95;

/**
 * Stage 2 confidence, routed by what actually triggered the verdict:
 *
 * - A "template" verdict triggered by structural evidence (verdictBasis:
 *   "structural" — same-store review homogeneity, recurring signature dishes,
 *   clustered posting) has nothing to do with how the *content* of this one
 *   review reads. Scoring it via the I/A/D agreement formula was the bug: a
 *   well-written, detailed ghost-written review "disagrees" with its own
 *   washed verdict on those dimensions, producing ~2% confidence and a
 *   near-1.0 weight — i.e. no actual filtering effect. So this branch scores
 *   confidence directly from the structural signal strength instead.
 * - Everything else (incentive keyword matches, content-driven "empty
 *   template" verdicts, and genuine clean verdicts) keeps the existing I/A/D
 *   agreement^1.5 formula unchanged.
 */
export function computeStage2Confidence(item: Stage2Item, context: Stage2SignalContext = {}): number {
  const isStructuralTemplate = item.isWashed && item.issueType === 'template' && item.verdictBasis === 'structural';

  if (isStructuralTemplate) {
    const similarComponent = Math.min((context.similarCount ?? 0) / STRUCTURAL_SIMILAR_COUNT_CAP, 1);
    const hotTermComponent = Math.min(context.hotTermMaxRatio ?? 0, 1);
    const nearbyComponent = Math.min((context.nearbyLongReviewCount ?? 0) / STRUCTURAL_NEARBY_LONG_REVIEW_CAP, 1);

    const compositeScore = 0.4 * similarComponent + 0.4 * hotTermComponent + 0.2 * nearbyComponent;
    const confidence = STRUCTURAL_CONFIDENCE_MIN + compositeScore * (STRUCTURAL_CONFIDENCE_MAX - STRUCTURAL_CONFIDENCE_MIN);
    return Math.round(Math.max(STRUCTURAL_CONFIDENCE_MIN, Math.min(STRUCTURAL_CONFIDENCE_MAX, confidence)));
  }

  const inc = item.incentiveIntensity || 3;
  const aut = item.sentimentAuthenticity || 3;
  const gra = item.descriptionGranularity || 3;

  // S_val: 0 (dimensions read as clean) .. 12 (dimensions read as washed),
  // independent of the model's own isWashed call.
  const sVal = (inc - 1) + (5 - aut) + (5 - gra);
  const washRatio = sVal / 12;

  // agreement: how strongly the I/A/D dimensions back up the model's binary
  // verdict. 1 = fully backed, 0 = fully contradicted, 0.5 = genuinely
  // ambiguous (dimensions don't lean either way — this is also what you get
  // when the model omits the dimension scores, since they default to 3/3/3).
  const agreement = item.isWashed ? washRatio : (1 - washRatio);

  // Full 0-100 range. The ^1.5 curve pulls the ambiguous midpoint
  // (agreement=0.5) down to ~35% instead of pinning it at 50+/60+, so a low
  // number visibly reads as "treat this verdict with caution" rather than
  // looking like moderate confidence.
  const confidence = Math.round(Math.pow(agreement, 1.5) * 100);
  return Math.max(0, Math.min(100, confidence));
}

/**
 * Merges Stage 2 (Gemini) results into a store's Stage-1-audited reviews.
 * Any review Stage 1 already reached a confident verdict on (issueType !== null)
 * was never sent to Gemini and must come out of this merge with its original
 * Stage 1 audit untouched — regression coverage for a bug where recomputing/
 * re-matching reviews let a Gemini result silently overwrite a Stage 1 verdict
 * that should have been left alone (see mergeStage2Results tests).
 */
export function mergeStage2Results(
  auditedReviews: (Review & { audit: AuditResult })[],
  aiStoreMap: { [username: string]: AuditResult }
): (Review & { audit: AuditResult })[] {
  return auditedReviews.map(r => {
    if (r.audit.issueType !== null) {
      return r;
    }
    if (aiStoreMap[r.username]) {
      return { ...r, audit: aiStoreMap[r.username] };
    }
    // Only 5-star reviews are Stage 2 candidates. Non-5-star reviews with
    // issueType null are genuinely clean — leave them at weight 1.0.
    // Marking them as unaudited (weight 0.65) would incorrectly downweight
    // low-star genuine reviews, pulling filteredRating above originalRating.
    if (r.stars !== 5) {
      return r;
    }
    // Stage 2 didn't cover this 5-star review — mark as unaudited so it gets
    // independent weight instead of masquerading as a confident clean verdict.
    return { ...r, audit: { ...r.audit, issueType: 'unaudited' as const } };
  });
}

/**
 * Aggregates already-audited reviews (Stage 1 only, or Stage 1 + Stage 2 merged)
 * into shop-level stats. This is the single source of truth for the weighting /
 * Trust Score / Filtered Rating math — call this again after merging in Stage 2
 * results instead of recomputing the formula inline.
 */
export function aggregateAuditedReviews(
  storeName: string,
  auditedReviews: (Review & { audit: AuditResult })[]
): ShopStats {
  const totalReviews = auditedReviews.length;
  if (totalReviews === 0) {
    return {
      storeName,
      originalRating: 0,
      filteredRating: 0,
      trustScore: 100,
      totalReviews: 0,
      suspiciousReviews: 0,
      issues: { timeAnomaly: 0, templateText: 0, vague: 0, noText: 0, lowInfo: 0, unaudited: 0 },
      ratingDistribution: {
        original: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 },
        filtered: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 },
      },
      auditedReviews: [],
    };
  }

  let originalSum = 0;
  let weightedSum = 0;
  let weightTotal = 0;
  let suspiciousReviewsCount = 0;

  const originalDistribution = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  const filteredDistribution = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };

  const issuesCount = {
    timeAnomaly: 0, // Maps to 'incentive' in our local model
    templateText: 0, // Maps to 'template'
    vague: 0, // Maps to 'discrepancy'
    noText: 0, // Maps to 'no_text'
    lowInfo: 0, // Maps to 'low_info'
    unaudited: 0, // Maps to 'unaudited'
  };

  // Weight for unaudited reviews: not derived from confidence. These reviews
  // were ambiguous enough to warrant Stage 2 but didn't get sent (production
  // cap or LLM drop). Treat them as moderately trustworthy — higher than
  // low_info (0.55) but lower than a reviewed clean verdict (0.8).
  // TODO: 暫定值，待參數掃描
  const UNAUDITED_WEIGHT = 0.65;

  auditedReviews.forEach(({ stars, audit }) => {
    // Unaudited reviews get a fixed weight, decoupled from the confidence system
    const weight = audit.issueType === 'unaudited'
      ? UNAUDITED_WEIGHT
      : audit.isWashed
        ? 1 - (audit.confidenceScore / 100)
        : 1.0;

    // Accumulate original stats
    originalSum += stars;
    originalDistribution[stars as 1 | 2 | 3 | 4 | 5] = (originalDistribution[stars as 1 | 2 | 3 | 4 | 5] || 0) + 1;

    // Accumulate weighted stats
    weightedSum += stars * weight;
    weightTotal += weight;

    // Accumulate weighted star distribution (rounded to 1 decimal to avoid floating point precision leaks)
    filteredDistribution[stars as 1 | 2 | 3 | 4 | 5] = parseFloat(
      ((filteredDistribution[stars as 1 | 2 | 3 | 4 | 5] || 0) + weight).toFixed(1)
    );

    if (audit.isWashed) {
      suspiciousReviewsCount++;
      if (audit.issueType === 'incentive') {
        issuesCount.timeAnomaly++;
      } else if (audit.issueType === 'template') {
        issuesCount.templateText++;
      } else if (audit.issueType === 'discrepancy') {
        issuesCount.vague++;
      }
    } else if (audit.issueType === 'no_text') {
      issuesCount.noText++;
    } else if (audit.issueType === 'low_info') {
      issuesCount.lowInfo++;
    } else if (audit.issueType === 'unaudited') {
      issuesCount.unaudited++;
    }
  });

  const originalRating = originalSum / totalReviews;
  const filteredRating = weightTotal > 0 ? weightedSum / weightTotal : originalRating;

  // Trust Score: an independent indicator of how suspicious a store's review
  // ecosystem is.  Displayed in the UI but does NOT modify filteredRating —
  // washed reviews are already down-weighted via the confidence-based weight
  // formula, so applying an additional star deduction from the same signal
  // would be double-punishment (removed in this version; see commit history).
  const trustScore = Math.max(0, 100 - (suspiciousReviewsCount / totalReviews) * 100);

  return {
    storeName,
    originalRating: parseFloat(originalRating.toFixed(2)),
    filteredRating: parseFloat(filteredRating.toFixed(2)),
    trustScore: parseFloat(trustScore.toFixed(0)),
    totalReviews,
    suspiciousReviews: suspiciousReviewsCount,
    issues: issuesCount,
    ratingDistribution: {
      original: originalDistribution,
      filtered: filteredDistribution,
    },
    auditedReviews,
  };
}

