import { Review } from './csvParser';

export interface AuditResult {
  isWashed: boolean;
  reason: string;
  confidenceScore: number;
  issueType: 'incentive' | 'template' | 'discrepancy' | 'no_text' | 'low_info' | null;
  reasoningPath?: string;
  incentiveIntensity?: number;
  sentimentAuthenticity?: number;
  descriptionGranularity?: number;
}

export interface TemporalContext {
  isSpikePeriod: boolean;
  daysElapsed: number;
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
  suspiciousReviews: number;
  issues: {
    timeAnomaly: number;
    templateText: number;
    vague: number;
  };
  ratingDistribution: {
    original: { [key: number]: number };
    filtered: { [key: number]: number };
  };
  auditedReviews: (Review & { audit: AuditResult })[];
}

// Bribe/Incentive keywords typically used in "Five-star reviews for free appetizers/drinks/discount"
const INCENTIVE_KEYWORDS = [
  '打卡', '活動', '評論送', '打卡送', '好評送', '免費送', 
  '送小菜', '送起司球', '送飲料', '送肉', '送單點', '送麻糬', '送奶酪'
];


export interface AuditReviewContext {
  isSpikePeriod?: boolean;
  similarCount?: number;
}



/**
 * Audit an individual review based on local heuristic rules. `context` carries
 * store-wide signals (spike period membership, cross-review similarity count)
 * that a single review can't determine on its own — pass it in from
 * computeShopStats, which has the full review list to derive them from.
 */
export function auditReview(review: Review, context: AuditReviewContext = {}): AuditResult {
  const text = review.text || '';

  // 0. No-text reviews (star rating only) carry no semantic signal to judge —
  // flag them as their own neutral category instead of falling through to
  // "no issue found" (which would wrongly count them as confidently clean).
  // They still count toward originalRating and are never sent to Stage 2 (nothing to reason about).
  if (text.trim().length === 0) {
    return {
      isWashed: false,
      reason: '評論未留下文字內容，僅提供星等，暫以中性權重採計。',
      confidenceScore: 50,
      issueType: 'no_text',
    };
  }

  // 1. Explicit Bribe/Incentive Check
  for (const keyword of INCENTIVE_KEYWORDS) {
    if (text.includes(keyword)) {
      return {
        isWashed: true,
        reason: `直接提及打卡/活動/贈送交易關鍵字：『${keyword}』。`,
        confidenceScore: 100,
        issueType: 'incentive',
      };
    }
  }

  // 2. Catch generic "送" only if accompanied by promotional keywords and not part of normal delivery/serving/hospitality terms
  if (text.includes('送')) {
    const excludes = [
      '外送', '配送', '送禮', '送給', '送餐', '送上', '送來', '送錯', '送客', '送走', '送出', 
      '推送', '面送', '送速度', '送口', '送入', '送到', '送達', '送桌', '補送', '送回', '菜梯送', 
      '端送', '發送', '傳送', '運送', '送進', '送過', '送風', '陸續送'
    ];
    
    const promoKeywords = [
      '打卡', '活動', '好評', '評論', '分享', '按讚', '追蹤', '關注', '五星', '五顆星', '5星', '5顆星',
      '推薦', '留言', '截圖', '貼文', '社群', 'IG', 'FB', '臉書', 'Google', 'google'
    ];
    
    const hasCleanSend = !excludes.some(ex => text.includes(ex));
    const hasPromoKeyword = promoKeywords.some(kw => text.includes(kw));
    
    if (hasCleanSend && hasPromoKeyword) {
      return {
        isWashed: true,
        reason: `直接匹配到打卡/活動/贈送交易關鍵字：『送』。`,
        confidenceScore: 100,
        issueType: 'incentive',
      };
    }
  }



  // Fallback (Non-washed in Stage 1)
  return {
    isWashed: false,
    reason: '評論無顯性利益交換跡象。',
    confidenceScore: 80,
    issueType: null,
  };
}

function getNGrams(str: string, n = 2): Set<string> {
  const ngrams = new Set<string>();
  const cleaned = str.replace(/\s+/g, '');
  if (cleaned.length < n) {
    if (cleaned.length > 0) ngrams.add(cleaned);
    return ngrams;
  }
  for (let i = 0; i <= cleaned.length - n; i++) {
    ngrams.add(cleaned.substring(i, i + n));
  }
  return ngrams;
}

function calculateJaccardSimilarity(s1: string, s2: string, n = 2): number {
  if (!s1 || !s2) return 0;
  if (s1 === s2) return 1;
  const set1 = getNGrams(s1, n);
  const set2 = getNGrams(s2, n);
  if (set1.size === 0 || set2.size === 0) return 0;

  let intersection = 0;
  set1.forEach(val => {
    if (set2.has(val)) {
      intersection++;
    }
  });

  const union = set1.size + set2.size - intersection;
  return intersection / union;
}

// Hard duplicate check: near-identical copy-paste text (2-gram, strict threshold).
const HARD_DUPLICATE_NGRAM = 2;
const HARD_DUPLICATE_THRESHOLD = 0.75;

// Soft structural-similarity signal fed to Gemini: broader n-gram, lower
// threshold, deliberately NOT used to auto-flag a verdict — genuine reviews of
// the same dish easily clear 45% on trigram overlap. It's cross-reference
// context for Stage 2, and (via similarCount) an escalation signal for
// Stage 1's low_info downgrade.
const SIMILARITY_SIGNAL_NGRAM = 3;
const SIMILARITY_SIGNAL_THRESHOLD = 0.45;
const SIMILARITY_MIN_TEXT_LENGTH = 6;

/**
 * Single pairwise pass computing both the existing hard duplicate flag and the
 * new soft similarity signals (maxSimilarity/similarCount), so the O(n²)
 * comparison only has to run once per store.
 */
export function computeSimilaritySignals(reviews: Review[]): SimilaritySignal[] {
  const n = reviews.length;
  const isDuplicate = new Array(n).fill(false);
  const maxSimilarity = new Array(n).fill(0);
  const similarCount = new Array(n).fill(0);

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const r1 = reviews[i];
      const r2 = reviews[j];
      if (r1.text.trim().length <= SIMILARITY_MIN_TEXT_LENGTH || r2.text.trim().length <= SIMILARITY_MIN_TEXT_LENGTH) {
        continue;
      }

      const exactSim = calculateJaccardSimilarity(r1.text, r2.text, HARD_DUPLICATE_NGRAM);
      if (exactSim > HARD_DUPLICATE_THRESHOLD) {
        isDuplicate[i] = true;
        isDuplicate[j] = true;
      }

      const structuralSim = calculateJaccardSimilarity(r1.text, r2.text, SIMILARITY_SIGNAL_NGRAM);
      if (structuralSim > maxSimilarity[i]) maxSimilarity[i] = structuralSim;
      if (structuralSim > maxSimilarity[j]) maxSimilarity[j] = structuralSim;
      if (structuralSim >= SIMILARITY_SIGNAL_THRESHOLD) {
        similarCount[i]++;
        similarCount[j]++;
      }
    }
  }

  return reviews.map((_, idx) => ({
    isDuplicate: isDuplicate[idx],
    maxSimilarity: Math.round(maxSimilarity[idx] * 100) / 100,
    similarCount: similarCount[idx],
  }));
}

// Candidate "hot term" phrase lengths — long enough to plausibly be a dish/
// product name (generic praise like "好吃"/"讚" is 1-2 chars and filtered out
// by this floor), short enough to still match across paraphrased mentions.
const HOT_TERM_MIN_LENGTH = 4;
const HOT_TERM_MAX_LENGTH = 8;
const HOT_TERM_MIN_REVIEW_COUNT = 3;
const HOT_TERM_MIN_COVERAGE_RATIO = 0.2;

function extractCandidateTerms(text: string): Set<string> {
  const cleaned = text.replace(/\s+/g, '');
  const terms = new Set<string>();
  for (let len = HOT_TERM_MIN_LENGTH; len <= HOT_TERM_MAX_LENGTH; len++) {
    for (let i = 0; i + len <= cleaned.length; i++) {
      terms.add(cleaned.substring(i, i + len));
    }
  }
  return terms;
}

/**
 * Identifies phrases (candidate dish/product names) that recur across a
 * disproportionate share of the store's 5-star reviews, then reports per
 * review how many of those "hot terms" it hits and the highest coverage
 * ratio among them. Reviews repeating the same signature phrase as many other
 * 5-star reviews are a template-farm tell, independent of how well-written
 * any single review looks.
 *
 * Candidate phrases of different lengths overlap heavily (e.g. every 4-8
 * length substring of a repeated dish name would otherwise each separately
 * qualify) — collapsed down to only the maximal (non-substring-of-another)
 * hot terms so hotTermCount reflects distinct phrases, not redundant overlaps.
 */
export function computeHotTermSignals(reviews: Review[]): HotTermSignal[] {
  const fiveStarReviews = reviews.filter(r => r.stars === 5 && r.text.trim().length > 0);
  const totalFiveStar = fiveStarReviews.length;

  if (totalFiveStar === 0) {
    return reviews.map(() => ({ hotTermCount: 0, hotTermMaxRatio: 0 }));
  }

  const termReviewCount = new Map<string, number>();
  fiveStarReviews.forEach(r => {
    extractCandidateTerms(r.text).forEach(term => {
      termReviewCount.set(term, (termReviewCount.get(term) || 0) + 1);
    });
  });

  const minCount = Math.max(HOT_TERM_MIN_REVIEW_COUNT, Math.ceil(totalFiveStar * HOT_TERM_MIN_COVERAGE_RATIO));
  const candidateTerms = Array.from(termReviewCount.keys()).filter(term => termReviewCount.get(term)! >= minCount);

  // Collapse to maximal terms: drop any candidate that's a substring of a
  // longer candidate also in the set (the longer one already implies it).
  const hotTerms = new Map<string, number>();
  candidateTerms.forEach(term => {
    const isSubstringOfAnother = candidateTerms.some(other => other !== term && other.length > term.length && other.includes(term));
    if (!isSubstringOfAnother) {
      hotTerms.set(term, termReviewCount.get(term)! / totalFiveStar);
    }
  });

  return reviews.map(review => {
    if (review.stars !== 5 || !review.text.trim()) {
      return { hotTermCount: 0, hotTermMaxRatio: 0 };
    }
    const terms = extractCandidateTerms(review.text);
    let count = 0;
    let maxRatio = 0;
    hotTerms.forEach((ratio, term) => {
      if (terms.has(term)) {
        count++;
        if (ratio > maxRatio) maxRatio = ratio;
      }
    });
    return { hotTermCount: count, hotTermMaxRatio: Math.round(maxRatio * 100) / 100 };
  });
}

const NEARBY_WINDOW_MS = 30 * 60 * 1000;
const LONG_REVIEW_MIN_LENGTH = 50;

/**
 * For each review, counts other reviews in the store that are "long"
 * (>50 chars) and posted within 30 minutes of it. Needs minute-level
 * timestamp precision to be meaningful (the Apify scraping path provides
 * this; the Playwright fallback's day-level dates make same-day reviews
 * trivially "nearby" — a known lower-fidelity edge case of that path).
 */
export function computeNearbyLongReviewCounts(reviews: Review[]): number[] {
  const timestamps = reviews.map(r => {
    if (!r.time) return null;
    const d = new Date(r.time);
    return isNaN(d.getTime()) ? null : d.getTime();
  });
  const isLong = reviews.map(r => r.text.trim().length > LONG_REVIEW_MIN_LENGTH);

  return reviews.map((_, i) => {
    const t = timestamps[i];
    if (t === null) return 0;
    let count = 0;
    for (let j = 0; j < reviews.length; j++) {
      if (j === i || !isLong[j]) continue;
      const tj = timestamps[j];
      if (tj === null) continue;
      if (Math.abs(tj - t) <= NEARBY_WINDOW_MS) count++;
    }
    return count;
  });
}

/**
 * Groups reviews by month and flags months where volume spikes to more than
 * 2x the store's monthly average (with at least 10 reviews that month) — the
 * signature of a concentrated check-in/promo review campaign.
 */
export function computeSpikeMonths(reviews: Review[]): Set<string> {
  const monthlyCounts: { [month: string]: number } = {};
  reviews.forEach(r => {
    if (r.time) {
      const month = r.time.substring(0, 7); // YYYY-MM
      if (/^\d{4}-\d{2}$/.test(month)) {
        monthlyCounts[month] = (monthlyCounts[month] || 0) + 1;
      }
    }
  });

  const monthKeys = Object.keys(monthlyCounts);
  const monthlyAverage = monthKeys.length > 0
    ? monthKeys.reduce((sum, k) => sum + monthlyCounts[k], 0) / monthKeys.length
    : 0;

  const spikeMonths = new Set<string>();
  monthKeys.forEach(month => {
    if (monthlyCounts[month] > 2 * monthlyAverage && monthlyCounts[month] >= 10) {
      spikeMonths.add(month);
    }
  });
  return spikeMonths;
}

/**
 * Shared temporal-context lookup (used both for the Stage 2 LLM payload and
 * for adjusting Stage 1 no-text reviews) — keeps spike/day-elapsed math in one place.
 */
export function getReviewTemporalContext(review: Review, spikeMonths: Set<string>, referenceDate: Date): TemporalContext {
  const month = review.time ? review.time.substring(0, 7) : '';
  const isSpikePeriod = spikeMonths.has(month);

  let daysElapsed = 0;
  if (review.time) {
    const reviewDate = new Date(review.time);
    if (!isNaN(reviewDate.getTime())) {
      const diffTime = referenceDate.getTime() - reviewDate.getTime();
      daysElapsed = Math.max(0, Math.floor(diffTime / (1000 * 60 * 60 * 24)));
    }
  }
  return { isSpikePeriod, daysElapsed };
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
      issues: { timeAnomaly: 0, templateText: 0, vague: 0 },
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
  };

  auditedReviews.forEach(({ stars, audit }) => {
    // Compute review weight based on confidence score (no binary hard cut-off!)
    const weight = audit.isWashed
      ? 1 - (audit.confidenceScore / 100)
      : (audit.confidenceScore / 100);

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
    }
  });

  const originalRating = originalSum / totalReviews;
  const filteredRating = weightTotal > 0 ? weightedSum / weightTotal : originalRating;

  // Trust Score: an independent indicator of how suspicious a store's review
  // ecosystem is.  Displayed in the UI but does NOT modify filteredRating —
  // washed reviews are already down-weighted via the confidence-based weight
  // formula, so applying an additional star deduction from the same signal
  // would be double-punishment (removed in this version; see commit history).
  const trustScore = Math.max(0, 100 - (suspiciousReviewsCount / totalReviews) * 100 * 2.0);

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

/**
 * Runs Stage 1 (local heuristics) over a restaurant's raw reviews and aggregates
 * the result into shop-level stats.
 */
export function computeShopStats(storeName: string, reviews: Review[]): ShopStats {
  if (reviews.length === 0) {
    return aggregateAuditedReviews(storeName, []);
  }

  // Precompute pairwise similarity (hard duplicate flag + soft maxSimilarity/
  // similarCount signals) and review-volume spike months once per store.
  const similaritySignals = computeSimilaritySignals(reviews);
  const spikeMonths = computeSpikeMonths(reviews);

  const auditedReviews = reviews.map((review, idx) => {
    const month = review.time ? review.time.substring(0, 7) : '';
    const isSpikePeriod = spikeMonths.has(month);
    const { isDuplicate, similarCount } = similaritySignals[idx];

    let audit = auditReview(review, { isSpikePeriod, similarCount });

    // Override with template flag if high similarity was detected
    if (!audit.isWashed && isDuplicate) {
      audit = {
        isWashed: true,
        reason: '⚠️ 檢測到此評論內文與店內其他評論相似度大於 75%，高度疑似模板洗評。',
        confidenceScore: 90,
        issueType: 'template'
      };
    }

    // No-text reviews start neutral, but a text-less 5-star review landing inside
    // a promo-driven review spike matches the classic "check-in for a free dish"
    // pattern — nudge it from neutral (0.5 weight) toward suspicious rather than
    // leaving it fully trusted just because there's no explicit keyword to match.
    if (audit.issueType === 'no_text' && review.stars === 5) {
      if (isSpikePeriod) {
        audit = {
          isWashed: true,
          reason: '⚠️ 評論未留下文字內容，且發布於評論量異常暴增期間，符合「無文字五星」集中出現的洗評典型特徵。',
          confidenceScore: 65,
          issueType: 'no_text',
        };
      }
    }

    return {
      ...review,
      audit,
    };
  });

  return aggregateAuditedReviews(storeName, auditedReviews);
}
