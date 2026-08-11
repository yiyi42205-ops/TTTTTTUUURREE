"""
TrueRating Stage 1 Rule Engine — the canonical Python implementation.

This module is the single source of truth for all Stage 1 heuristic rules.
Both the live backend endpoint (POST /api/audit-rules) and the offline
evaluation script (eval/evaluate_v2.py) import from here.

Previously, this logic lived in two mirrored implementations:
  - auditEngine.ts (frontend, live)
  - evaluate_v2.py (offline evaluator)
Now it lives here only.
"""
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


# ─── 參數設定 ───────────────────────────────────────────────

@dataclass(frozen=True)
class RuleConfig:
    """規則引擎的所有門檻值集中於此一個物件，供參數掃描逐組覆寫。"""
    label: str = 'default'
    jaccard_threshold: float = 0.75
    min_template_chars: int = 6
    similarity_ngram: int = 3
    similarity_threshold: float = 0.45
    low_info_escalation_similar_count: int = 2
    wash_verdict_threshold: float = 0.03       # evaluation-only (store-level binary)


# ─── 常數 ───────────────────────────────────────────────────

INCENTIVE_KEYWORDS = [
    '打卡', '活動', '評論送', '打卡送', '好評送', '免費送',
    '送小菜', '送起司球', '送飲料', '送肉', '送單點', '送麻糬', '送奶酪',
]

# Additional keywords that trigger incentive check without the "送" context
NON_SEND_KEYWORDS = ['打卡', '活動', '五星', '五顆星', '好評']

# "送" contextual check — ported from auditEngine.ts lines 107-129
SEND_EXCLUDES = [
    '外送', '配送', '送禮', '送給', '送餐', '送上', '送來', '送錯', '送客',
    '送走', '送出', '推送', '面送', '送速度', '送口', '送入', '送到', '送達',
    '送桌', '補送', '送回', '菜梯送', '端送', '發送', '傳送', '運送', '送進',
    '送過', '送風', '陸續送',
]

SEND_PROMO_KEYWORDS = [
    '打卡', '活動', '好評', '評論', '分享', '按讚', '追蹤', '關注',
    '五星', '五顆星', '5星', '5顆星', '推薦', '留言', '截圖', '貼文',
    '社群', 'IG', 'FB', '臉書', 'Google', 'google',
]

EMPTY_WORDS = {
    '讚', '超讚', '好吃', '推', '棒', '美味', '讚的', '讚啦', '很讚', '推推',
    '讚喔', '好喝', '讚讚', '不錯', '好讚', '好店', '優', '優質', '讚哩',
    '讚啊', '極推', '大推', '好食', '真讚', '好美味',
}

REPEATING_PRAISE_RE = re.compile(r'^(讚+|推+|棒+|好+|讚+推+)$')
STRIP_PUNCT_RE = re.compile(r'[\s!！~～.。?？,，、]')

# Hot term detection constants
HOT_TERM_MIN_LENGTH = 4
HOT_TERM_MAX_LENGTH = 8
HOT_TERM_MIN_REVIEW_COUNT = 3
HOT_TERM_MIN_COVERAGE_RATIO = 0.2

# Nearby long review constants
NEARBY_WINDOW_SECONDS = 30 * 60
LONG_REVIEW_MIN_LENGTH = 50


# ─── Helper functions ────────────────────────────────────────

def get_ngram(text, n=2):
    text = re.sub(r'\s+', '', text or '')
    return set(text[i:i + n] for i in range(len(text) - n + 1)) if len(text) >= n else set()


def jaccard(a, b):
    if not a or not b:
        return 0
    return len(a & b) / len(a | b)


def _extract_candidate_terms(text):
    cleaned = re.sub(r'\s+', '', text or '')
    terms = set()
    for length in range(HOT_TERM_MIN_LENGTH, HOT_TERM_MAX_LENGTH + 1):
        for i in range(0, len(cleaned) - length + 1):
            terms.add(cleaned[i:i + length])
    return terms


def _parse_timestamp(time_str):
    if not time_str:
        return None
    try:
        return datetime.fromisoformat(time_str.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def is_generic_short_review(text, stars):
    if stars < 4:
        return False
    cleaned = STRIP_PUNCT_RE.sub('', text or '')
    return cleaned in EMPTY_WORDS or bool(REPEATING_PRAISE_RE.match(cleaned))


# ─── Signal detection functions ──────────────────────────────

def detect_templates(reviews, config: RuleConfig = None):
    """Hard duplicate detection via 2-gram Jaccard."""
    if config is None:
        config = RuleConfig()
    grams = []
    for r in reviews:
        text = r.get('text', '') or ''
        cleaned = re.sub(r'\s+', '', text)
        grams.append(get_ngram(text, 2) if len(cleaned) > config.min_template_chars else None)
    flags = [False] * len(reviews)
    for i in range(len(reviews)):
        if grams[i] is None:
            continue
        for j in range(i + 1, len(reviews)):
            if grams[j] is None:
                continue
            if jaccard(grams[i], grams[j]) > config.jaccard_threshold:
                flags[i] = flags[j] = True
    return flags


def detect_similarity_signals(reviews, config: RuleConfig = None):
    """Soft structural similarity signals (n-gram Jaccard)."""
    if config is None:
        config = RuleConfig()
    grams = []
    for r in reviews:
        text = r.get('text', '') or ''
        cleaned = re.sub(r'\s+', '', text)
        grams.append(get_ngram(text, config.similarity_ngram) if len(cleaned) > config.min_template_chars else None)

    max_similarity = [0.0] * len(reviews)
    similar_count = [0] * len(reviews)
    for i in range(len(reviews)):
        if grams[i] is None:
            continue
        for j in range(i + 1, len(reviews)):
            if grams[j] is None:
                continue
            sim = jaccard(grams[i], grams[j])
            if sim > max_similarity[i]:
                max_similarity[i] = sim
            if sim > max_similarity[j]:
                max_similarity[j] = sim
            if sim >= config.similarity_threshold:
                similar_count[i] += 1
                similar_count[j] += 1
    return max_similarity, similar_count


def detect_hot_term_signals(reviews):
    """Identifies recurring dish-name phrases across 5-star reviews."""
    five_star_reviews = [r for r in reviews if r.get('stars') == 5 and (r.get('text') or '').strip()]
    total_five_star = len(five_star_reviews)

    if total_five_star == 0:
        return [0] * len(reviews), [0.0] * len(reviews)

    term_review_count = defaultdict(int)
    for r in five_star_reviews:
        for term in _extract_candidate_terms(r.get('text', '')):
            term_review_count[term] += 1

    min_count = max(HOT_TERM_MIN_REVIEW_COUNT, math.ceil(total_five_star * HOT_TERM_MIN_COVERAGE_RATIO))
    candidate_terms = [term for term, count in term_review_count.items() if count >= min_count]

    hot_terms = {}
    for term in candidate_terms:
        is_substring_of_another = any(
            other != term and len(other) > len(term) and term in other
            for other in candidate_terms
        )
        if not is_substring_of_another:
            hot_terms[term] = term_review_count[term] / total_five_star

    hot_term_counts = []
    hot_term_max_ratios = []
    for r in reviews:
        text = (r.get('text') or '').strip()
        if r.get('stars') != 5 or not text:
            hot_term_counts.append(0)
            hot_term_max_ratios.append(0.0)
            continue
        terms = _extract_candidate_terms(r.get('text', ''))
        count = 0
        max_ratio = 0.0
        for term, ratio in hot_terms.items():
            if term in terms:
                count += 1
                if ratio > max_ratio:
                    max_ratio = ratio
        hot_term_counts.append(count)
        hot_term_max_ratios.append(round(max_ratio, 2))
    return hot_term_counts, hot_term_max_ratios


def detect_nearby_long_review_counts(reviews):
    """Counts long reviews posted within 30 minutes of each review."""
    timestamps = [_parse_timestamp(r.get('time', '')) for r in reviews]
    is_long = [len((r.get('text') or '').strip()) > LONG_REVIEW_MIN_LENGTH for r in reviews]

    counts = []
    for i, t in enumerate(timestamps):
        if t is None:
            counts.append(0)
            continue
        count = 0
        for j, tj in enumerate(timestamps):
            if j == i or not is_long[j] or tj is None:
                continue
            if abs(tj - t) <= NEARBY_WINDOW_SECONDS:
                count += 1
        counts.append(count)
    return counts


def detect_spike_months(reviews):
    """Flags months with review volume > 2x average and >= 10 reviews."""
    counts = defaultdict(int)
    months = []
    for r in reviews:
        time_str = r.get('time', '') or ''
        try:
            dt = datetime.strptime(time_str[:10], '%Y-%m-%d')
            mk = dt.strftime('%Y-%m')
            counts[mk] += 1
            months.append(mk)
        except (ValueError, TypeError):
            months.append(None)
    if not counts:
        return [False] * len(reviews), set()
    avg = sum(counts.values()) / len(counts)
    spike = {m for m, c in counts.items() if c > avg * 2 and c >= 10}
    return [(m in spike) if m else False for m in months], spike


# ─── Per-review audit (mirrors auditEngine.ts auditReview) ───

def _check_incentive_keywords(text):
    """Check for explicit incentive keywords."""
    for kw in INCENTIVE_KEYWORDS:
        if kw in text:
            return kw
    return None


def _check_send_context(text):
    """Check for contextual '送' usage with promo keywords (auditEngine.ts lines 107-129)."""
    if '送' not in text:
        return False
    has_clean_send = not any(ex in text for ex in SEND_EXCLUDES)
    has_promo_keyword = any(kw in text for kw in SEND_PROMO_KEYWORDS)
    return has_clean_send and has_promo_keyword


def audit_review(review, context=None, config: RuleConfig = None):
    """Per-review Stage 1 heuristic audit. Returns an AuditResult dict.

    Args:
        review: dict with 'text', 'stars', 'username', 'time', etc.
        context: dict with optional 'isSpikePeriod' (bool), 'similarCount' (int)
        config: RuleConfig for threshold values
    """
    if config is None:
        config = RuleConfig()
    if context is None:
        context = {}

    text = review.get('text', '') or ''
    try:
        stars = int(review.get('stars') or 0)
    except (ValueError, TypeError):
        stars = 0

    # 0. No-text reviews
    if text.strip() == '':
        return {
            'isWashed': False,
            'reason': '評論未留下文字內容，僅提供星等，暫以中性權重採計。',
            'confidenceScore': 50,
            'issueType': 'no_text',
        }

    # 1. Explicit incentive keyword check
    matched_kw = _check_incentive_keywords(text)
    if matched_kw:
        return {
            'isWashed': True,
            'reason': f'直接提及打卡/活動/贈送交易關鍵字：『{matched_kw}』。',
            'confidenceScore': 100,
            'issueType': 'incentive',
        }

    # 2. Contextual "送" check
    if _check_send_context(text):
        return {
            'isWashed': True,
            'reason': '直接匹配到打卡/活動/贈送交易關鍵字：『送』。',
            'confidenceScore': 100,
            'issueType': 'incentive',
        }

    # 3. Short generic review / low_info
    if is_generic_short_review(text, stars):
        is_escalated = bool(context.get('isSpikePeriod')) or \
            (context.get('similarCount', 0) >= config.low_info_escalation_similar_count)
        if is_escalated:
            return {
                'isWashed': True,
                'reason': f'⚠️ 評論為極短空洞模板（『{text}』），且發布於評論量異常暴增期間或與店內其他評論高度相似，判定為洗評。',
                'confidenceScore': 85,
                'issueType': 'template',
            }
        return {
            'isWashed': False,
            'reason': f'評論字數過短、內容空泛（『{text}』），屬低資訊評論而非洗評證據，暫以中性偏低權重採計。',
            'confidenceScore': 55,
            'issueType': 'low_info',
        }

    # 4. Fallback — ambiguous, send to Stage 2
    return {
        'isWashed': False,
        'reason': '評論無顯性利益交換跡象。',
        'confidenceScore': 80,
        'issueType': None,
    }


# ─── Store-level orchestrator (mirrors computeShopStats) ─────

def run_stage1_audit(reviews, config: RuleConfig = None):
    """Run the full Stage 1 rule engine over a list of normalized reviews.

    Returns a dict with:
      - auditedReviews: list of review dicts with 'audit' field attached
      - signals: precomputed cross-review signals for Stage 2
    """
    if config is None:
        config = RuleConfig()

    if not reviews:
        return {
            'auditedReviews': [],
            'signals': {
                'similarity': [],
                'hotTerm': [],
                'nearbyLongReviewCounts': [],
                'spikeMonths': [],
            },
        }

    # Precompute cross-review signals
    template_flags = detect_templates(reviews, config)
    max_similarity, similar_counts = detect_similarity_signals(reviews, config)
    spike_flags, spike_months = detect_spike_months(reviews)
    hot_term_counts, hot_term_max_ratios = detect_hot_term_signals(reviews)
    nearby_long_review_counts = detect_nearby_long_review_counts(reviews)

    # Exact-match counting for generic short reviews.
    # These are too short for n-gram Jaccard (len <= min_template_chars) so
    # detect_similarity_signals always returns similarCount=0 for them.
    # Count how many other reviews share the exact same cleaned text instead.
    short_exact_counts = [0] * len(reviews)
    cleaned_texts = []
    is_generic_short = []
    for r in reviews:
        text = r.get('text', '') or ''
        try:
            stars = int(r.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        cleaned = STRIP_PUNCT_RE.sub('', text)
        is_short = is_generic_short_review(text, stars)
        cleaned_texts.append(cleaned)
        is_generic_short.append(is_short)

    # Build frequency map of cleaned texts among generic short reviews
    short_text_freq = defaultdict(int)
    for i, is_short in enumerate(is_generic_short):
        if is_short:
            short_text_freq[cleaned_texts[i]] += 1
    for i, is_short in enumerate(is_generic_short):
        if is_short:
            short_exact_counts[i] = short_text_freq[cleaned_texts[i]] - 1  # exclude self

    # Per-review audit
    audited = []
    for i, review in enumerate(reviews):
        is_spike = spike_flags[i]
        sim_count = max(similar_counts[i], short_exact_counts[i])

        audit = audit_review(review, {
            'isSpikePeriod': is_spike,
            'similarCount': sim_count,
        }, config)

        # Override: hard duplicate detection
        if not audit['isWashed'] and template_flags[i]:
            audit = {
                'isWashed': True,
                'reason': '⚠️ 檢測到此評論內文與店內其他評論相似度大於 75%，高度疑似模板洗評。',
                'confidenceScore': 90,
                'issueType': 'template',
            }

        # Override: no_text 5-star in spike period
        try:
            stars = int(review.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        if audit['issueType'] == 'no_text' and stars == 5 and is_spike:
            audit = {
                'isWashed': True,
                'reason': '⚠️ 評論未留下文字內容，且發布於評論量異常暴增期間，符合「無文字五星」集中出現的洗評典型特徵。',
                'confidenceScore': 65,
                'issueType': 'no_text',
            }

        audited.append({
            **review,
            'audit': audit,
        })

    # Build signals response
    similarity_signals = [
        {
            'isDuplicate': template_flags[i],
            'maxSimilarity': round(max_similarity[i], 2),
            'similarCount': max(similar_counts[i], short_exact_counts[i]),
        }
        for i in range(len(reviews))
    ]
    hot_term_signals = [
        {
            'hotTermCount': hot_term_counts[i],
            'hotTermMaxRatio': hot_term_max_ratios[i],
        }
        for i in range(len(reviews))
    ]

    return {
        'auditedReviews': audited,
        'signals': {
            'similarity': similarity_signals,
            'hotTerm': hot_term_signals,
            'nearbyLongReviewCounts': nearby_long_review_counts,
            'spikeMonths': sorted(spike_months),
        },
    }
