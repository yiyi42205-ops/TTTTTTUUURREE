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
import random
import re
import zlib
from collections import defaultdict

from langdetect import detect, LangDetectException, DetectorFactory
DetectorFactory.seed = 0
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
    spike_threshold: float = 0.80
    spike_min_count: int = 10
    spike_window_size: int = 20
    no_text_escalation_ratio: float = 0.20
    structural_min_similarity: float = 0.55
    structural_min_similar_count: int = 2
    structural_min_hot_term_count: int = 2
    structural_min_hot_term_ratio: float = 0.3
    wash_verdict_threshold: float = 0.03       # evaluation-only (store-level binary)


# ─── 常數 ───────────────────────────────────────────────────

# --- Incentive detection: three-factor semantic approach (Issue #87) ---
#
# High confidence (direct washed): 評論行為 + 交換關係 + 利益 all present
#   e.g. 「五星評論送雞翅」「評五星送可樂」「留評論送王子麵」
#
# Medium confidence (suspicious, send to Stage 2): only two factors
#   e.g. 「打卡送飲料」(missing explicit review/star action)
#
# No match: only one factor or ambiguous keyword in non-promo context
#   e.g. 「活動中心」「拍照打卡」「老闆送菜」

# Factor 1: Review/rating action keywords (includes social sharing actions
# that are commonly tied to review incentive campaigns)
REVIEW_ACTION_KEYWORDS = [
    '評論', '評價', '好評', '留言', '五星', '五顆星', '5星', '5顆星',
    'Google', 'google', '谷歌',
    '分享', '按讚', '追蹤', '貼文', '截圖',  # social actions tied to campaigns
]

# Factor 2: Exchange relationship keywords
EXCHANGE_KEYWORDS = [
    '送', '贈', '換', '免費', '招待', '折扣', '優惠',
]

# Factor 3: Compound patterns that directly imply review-for-reward
# These are high-confidence — two+ factors baked into one phrase
INCENTIVE_COMPOUND_KEYWORDS = [
    '評論送', '好評送', '打卡送',
    '送小菜', '送起司球', '送飲料', '送肉', '送單點', '送麻糬', '送奶酪',
]

# 「免費送」needs context — "滿150元免費送" is a purchase threshold promo
FREE_SEND_EXCLUDE_RE = re.compile(r'滿\d+.*免費送|消費.*免費送|免費送\s*[，,]?\s*外送')

# Negation prefixes that invalidate compound keyword matches
NEGATION_PREFIXES = ['沒有', '沒', '不', '未', '非', '無']

# "送" contextual check — ported from auditEngine.ts lines 107-129
SEND_EXCLUDES = [
    '外送', '配送', '送禮', '送給', '送餐', '送上', '送來', '送錯', '送客',
    '送走', '送出', '推送', '面送', '送速度', '送口', '送入', '送到', '送達',
    '送桌', '補送', '送回', '菜梯送', '端送', '發送', '傳送', '運送', '送進',
    '送過', '送風', '陸續送',
    # Additional excludes for hospitality/retail (Issue #87)
    '老闆送', '老闆娘送', '店家送', '店員送', '師傅送',  # 招待
    '附送', '隨餐送',                                     # 餐點搭贈
    '送人', '送朋友', '送家人', '送親友', '送同事',       # 送禮
]

# "買N送N" is a normal retail promotion, not review incentive
BUY_N_SEND_N_RE = re.compile(r'買\d+送\d+')

# 「打卡」exclusion contexts — photo check-in, revisit, not review incentive
CHECKIN_EXCLUDE_CONTEXTS = [
    '拍照打卡', '網美打卡', '打卡拍照', '打卡景點', '打卡點',
    '打卡留念', '打卡紀念', '來打卡', '回來打卡', '再打卡',
    '值得打卡', '想打卡', '不打卡', '沒打卡', '沒有打卡',
    '不用打卡', '不急著打卡', '不會打卡', '不刻意打卡',
    'IG打卡', 'ig打卡', 'FB打卡', 'fb打卡',
]

# 「活動」exclusion contexts — event/venue, not promo
ACTIVITY_EXCLUDE_CONTEXTS = [
    '活動中心', '活動空間', '辦活動', '舉辦活動', '參加活動',
    '同學會活動', '公司活動', '親子活動', '家庭活動', '團體活動',
    '休閒活動', '戶外活動', 'DIY活動', '體驗活動', '藝術活動',
    '主題活動', '聯名活動', '活動場地', '活動需要',
    '一直活動',  # 動詞用法
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

# Structural confidence constants (ported from auditEngine.ts)
STRUCTURAL_SIMILAR_COUNT_CAP = 5
STRUCTURAL_NEARBY_LONG_REVIEW_CAP = 5
STRUCTURAL_CONFIDENCE_MIN = 60
STRUCTURAL_CONFIDENCE_MAX = 95


# ─── Helper functions ────────────────────────────────────────

HASHTAG_RE = re.compile(r'#\S+')


def _strip_hashtags(text: str) -> str:
    """Remove #hashtag tokens before computing structural signals."""
    return HASHTAG_RE.sub('', text)


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


# ─── Structural template detection (rule 2.6) ────────────────

def hits_structural_template(sig: dict, config: RuleConfig = None) -> bool:
    """Rule 2.6: structural homogeneity template. Thresholds from prompt v2, provisional."""
    if config is None:
        config = RuleConfig()
    a = sig['maxSimilarity'] >= config.structural_min_similarity and sig['similarCount'] >= config.structural_min_similar_count
    b = sig['hotTermCount'] >= config.structural_min_hot_term_count and sig['hotTermMaxRatio'] >= config.structural_min_hot_term_ratio
    return a or b


def compute_structural_confidence(similar_count: int, hot_term_max_ratio: float, nearby_long_review_count: int) -> int:
    """Structural confidence from signal strength, mapped to 60-95.
    Ported from auditEngine.ts computeStage2Confidence structural branch."""
    similar_component = min(similar_count / STRUCTURAL_SIMILAR_COUNT_CAP, 1)
    hot_term_component = min(hot_term_max_ratio, 1)
    nearby_component = min(nearby_long_review_count / STRUCTURAL_NEARBY_LONG_REVIEW_CAP, 1)
    composite = 0.4 * similar_component + 0.4 * hot_term_component + 0.2 * nearby_component
    confidence = STRUCTURAL_CONFIDENCE_MIN + composite * (STRUCTURAL_CONFIDENCE_MAX - STRUCTURAL_CONFIDENCE_MIN)
    return round(max(STRUCTURAL_CONFIDENCE_MIN, min(STRUCTURAL_CONFIDENCE_MAX, confidence)))


# ─── MinHash LSH for O(N) template detection ──────────────────

_NUM_PERM = 10
_MINHASH_PRIME = 4294967311
_rng = random.Random(42)
_MINHASH_FUNCS = [(_rng.randint(1, _MINHASH_PRIME - 1), _rng.randint(0, _MINHASH_PRIME - 1)) for _ in range(_NUM_PERM)]


def _minhash(ngrams):
    """Compute MinHash signature for a set of n-grams."""
    if not ngrams:
        return None
    hashed_grams = [zlib.crc32(g.encode('utf-8')) & 0xFFFFFFFF for g in ngrams]
    signature = []
    for a, b in _MINHASH_FUNCS:
        signature.append(min((a * x + b) % _MINHASH_PRIME for x in hashed_grams))
    return signature


# ─── Signal detection functions ──────────────────────────────

def detect_templates(reviews, config: RuleConfig = None):
    """Hard duplicate detection via MinHash LSH with exact Jaccard fallback."""
    if config is None:
        config = RuleConfig()

    grams_list = []
    signatures = []
    for r in reviews:
        text = _strip_hashtags(r.get('text', '') or '')
        cleaned = re.sub(r'\s+', '', text)
        if len(cleaned) > config.min_template_chars:
            grams = get_ngram(text, 2)
            grams_list.append(grams)
            signatures.append(_minhash(grams))
        else:
            grams_list.append(None)
            signatures.append(None)

    flags = [False] * len(reviews)

    # LSH bucketing (b=5 bands, r=2 rows per band)
    b = 5
    r = 2
    buckets = defaultdict(list)

    for i, sig in enumerate(signatures):
        if sig is None:
            continue
        for band_idx in range(b):
            band = tuple(sig[band_idx * r : (band_idx + 1) * r])
            bucket_key = (band_idx, zlib.crc32(str(band).encode()) & 0xFFFFFFFF)

            for j in buckets[bucket_key]:
                if not flags[i] or not flags[j]:
                    if jaccard(grams_list[i], grams_list[j]) > config.jaccard_threshold:
                        flags[i] = flags[j] = True

            buckets[bucket_key].append(i)

    return flags


def detect_similarity_signals(reviews, config: RuleConfig = None):
    """Soft structural similarity signals (n-gram Jaccard)."""
    if config is None:
        config = RuleConfig()
    grams = []
    for r in reviews:
        text = _strip_hashtags(r.get('text', '') or '')
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
        for term in _extract_candidate_terms(_strip_hashtags(r.get('text', ''))):
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
        terms = _extract_candidate_terms(_strip_hashtags(r.get('text', '')))
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


def detect_no_text_ratio(reviews: list[dict]) -> float:
    """Computes the ratio of no-text (empty) reviews among all reviews."""
    if not reviews:
        return 0.0
    no_text_count = sum(1 for r in reviews if not (r.get('text', '') or '').strip())
    return round(no_text_count / len(reviews), 4)


def detect_language_ratio(reviews: list[dict]) -> float:
    """Computes the ratio of non-Chinese reviews among text-bearing reviews.

    Uses langdetect to identify language. Reviews without text are excluded.
    Skips very short texts (< 5 chars) where langdetect is unreliable.
    Returns 0.0 if no eligible text reviews exist.
    """
    text_reviews = [r for r in reviews if (r.get('text', '') or '').strip()]
    if not text_reviews:
        return 0.0

    non_zh_count = 0
    eligible = 0
    for r in text_reviews:
        text = r['text'].strip()
        if len(text) < 5:
            continue  # Skip very short texts where detection is unreliable
        eligible += 1
        try:
            lang = detect(text)
            if lang not in ('zh-cn', 'zh-tw'):
                # langdetect frequently misclassifies short Chinese text as Korean or Japanese 
                # due to shared CJK chars, so we make an exception for short texts.
                if lang in ('ko', 'ja') and len(text) < 20:
                    pass
                else:
                    non_zh_count += 1
        except LangDetectException:
            pass
    if eligible == 0:
        return 0.0
    return round(non_zh_count / eligible, 4)


def detect_spike_months(reviews, config: RuleConfig = None):
    """Detect review-density spikes using a sliding window over review order.

    Reviews are assumed to arrive sorted by time (newest-first from the
    scraper).  The function uses review *order* directly — no date parsing
    or re-sorting — so it works even when date strings are imprecise
    (e.g. Apify's relative dates like "一年前" all mapping to the same day).

    A review is considered "suspicious" if it is 5-star AND has ≤4 chars
    of text (i.e. empty or near-empty positive reviews).

    A sliding window of *spike_window_size* consecutive reviews is moved
    across the list.  If the fraction of suspicious reviews in the window
    meets or exceeds *spike_threshold*, every review in the window is
    flagged as part of a spike.

    Returns:
      - flags: list[bool] per review (True = in a spike region)
      - spike_months: set[str] of YYYY-MM strings that contain spike reviews
        (kept for backward compat with signals output)
    """
    if config is None:
        config = RuleConfig()

    n = len(reviews)
    if n < config.spike_min_count:
        return [False] * n, set()

    # Mark each review as suspicious (5-star + effectively empty text)
    suspicious = []
    for r in reviews:
        try:
            stars = int(r.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        text = (r.get('text', '') or '').strip()
        suspicious.append(stars == 5 and len(text) <= 4)

    # Sliding window — count suspicious reviews in each window position
    w = min(config.spike_window_size, n)
    threshold_count = math.ceil(w * config.spike_threshold)
    flags = [False] * n

    # Initial window count
    sus_count = sum(suspicious[:w])

    for start in range(n - w + 1):
        if start > 0:
            # Slide: remove left, add right
            sus_count -= suspicious[start - 1]
            sus_count += suspicious[start + w - 1]

        if sus_count >= threshold_count:
            for j in range(start, start + w):
                flags[j] = True

    # Build spike_months set for backward compat (parse dates where available)
    spike_months = set()
    for i, flagged in enumerate(flags):
        if flagged:
            time_str = (reviews[i].get('time', '') or '')[:10]
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d')
                spike_months.add(dt.strftime('%Y-%m'))
            except (ValueError, TypeError):
                pass

    return flags, spike_months


# ─── Per-review audit (mirrors auditEngine.ts auditReview) ───

def _check_incentive_semantic(text):
    """Three-factor semantic incentive detection (Issue #87).

    Returns:
        ('high', matched_desc)   — direct review-for-reward, mark as washed
        ('medium', matched_desc) — suspicious but ambiguous, send to Stage 2
        None                     — no incentive signal
    """
    # 1. Compound keywords — high confidence by themselves
    #    Skip if preceded by negation within 5 chars (e.g. "沒有參加評論送甜點活動")
    for kw in INCENTIVE_COMPOUND_KEYWORDS:
        if kw in text:
            idx = text.index(kw)
            window = text[max(0, idx - 5):idx]
            negated = any(neg in window for neg in NEGATION_PREFIXES)
            if not negated:
                return ('high', kw)

    # 「免費送」— only if not a purchase-threshold promo
    if '免費送' in text and not FREE_SEND_EXCLUDE_RE.search(text):
        idx = text.index('免費送')
        window = text[max(0, idx - 5):idx]
        negated = any(neg in window for neg in NEGATION_PREFIXES)
        if not negated:
            return ('high', '免費送')

    # 2. Three-factor check: review action + exchange + present in text
    has_review_action = any(kw in text for kw in REVIEW_ACTION_KEYWORDS)
    has_exchange = _has_clean_exchange(text)

    if has_review_action and has_exchange:
        # Check if any review action keyword is negated (e.g. "沒有參加評論送")
        all_negated = True
        for kw in REVIEW_ACTION_KEYWORDS:
            if kw in text:
                idx = text.index(kw)
                window = text[max(0, idx - 5):idx]
                if not any(neg in window for neg in NEGATION_PREFIXES):
                    all_negated = False
                    break
        if not all_negated:
            return ('high', '評論行為＋交換關係')

    # 3. 「打卡」— only suspicious if paired with exchange, and not in
    #    photo/revisit context
    if '打卡' in text:
        if not any(ex in text for ex in CHECKIN_EXCLUDE_CONTEXTS):
            if has_exchange:
                return ('medium', '打卡＋交換關係')

    # 4. 「活動」— only suspicious if paired with exchange, and not in
    #    event/venue context
    if '活動' in text:
        if not any(ex in text for ex in ACTIVITY_EXCLUDE_CONTEXTS):
            if has_exchange:
                return ('medium', '活動＋交換關係')

    return None


def _has_clean_exchange(text):
    """Check if text contains an exchange keyword in a non-excluded context."""
    if '送' in text:
        if BUY_N_SEND_N_RE.search(text):
            return False
        if not any(ex in text for ex in SEND_EXCLUDES):
            return True
    return any(kw in text for kw in EXCHANGE_KEYWORDS if kw != '送' and kw in text)


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
    # Most users simply tap a star without writing — this is normal behaviour,
    # not a washing signal.  However, clusters of blank 5-star reviews during
    # spike periods or when many such reviews exist are a classic wash pattern.
    # Uses the same escalation framework as low_info (spike OR count ≥ threshold).
    if text.strip() == '':
        if stars == 5:
            is_escalated = bool(context.get('isSpikePeriod')) or \
                (context.get('noTextRatio', 0) >= config.no_text_escalation_ratio)
            if is_escalated:
                return {
                    'isWashed': True,
                    'reason': '⚠️ 評論未留下文字內容，且處於評論量異常暴增期間或店內無文字五星評論數量偏高，符合洗評典型特徵。',
                    'confidenceScore': 75,
                    'issueType': 'no_text',
                }
        return {
            'isWashed': False,
            'reason': '評論未留下文字內容，僅提供星等，以近正常權重採計。',
            'confidenceScore': 85,
            'issueType': 'no_text',
        }

    # 1. Semantic incentive check (Issue #87: three-factor approach)
    # Stars ≤ 3: the reviewer is reporting/complaining about wash campaigns,
    # not participating in them (e.g. "洗評論送紅茶，給一星剛好"). Issue #59.
    incentive_result = _check_incentive_semantic(text)
    if incentive_result:
        level, matched_desc = incentive_result
        if stars <= 3:
            return {
                'isWashed': False,
                'reason': f'評論提及促銷關鍵字『{matched_desc}』，但星等僅 {stars} 星，判定為揭發/抱怨而非參與洗評。',
                'confidenceScore': 80,
                'issueType': None,
            }
        if level == 'high':
            return {
                'isWashed': True,
                'reason': f'偵測到評論誘因：『{matched_desc}』。',
                'confidenceScore': 100,
                'issueType': 'incentive',
            }
        # medium: suspicious but ambiguous — send to Stage 2 for LLM judgment
        if level == 'medium':
            return {
                'isWashed': False,
                'reason': f'疑似評論誘因（{matched_desc}），但語境不明確，交由 AI 複審。',
                'confidenceScore': 50,
                'issueType': None,
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
                'noTextRatio': 0.0,
                'foreignLanguageRatio': 0.0,
                'whistleblowerCount': 0,
                'whistleblowerReviews': [],
            },
        }

    # Precompute cross-review signals
    template_flags = detect_templates(reviews, config)
    max_similarity, similar_counts = detect_similarity_signals(reviews, config)
    spike_flags, spike_months = detect_spike_months(reviews, config)
    hot_term_counts, hot_term_max_ratios = detect_hot_term_signals(reviews)
    nearby_long_review_counts = detect_nearby_long_review_counts(reviews)
    no_text_ratio = detect_no_text_ratio(reviews)
    foreign_language_ratio = detect_language_ratio(reviews)

    # Exact-match counting for short positive reviews.
    # These are too short for n-gram Jaccard (len <= min_template_chars) so
    # detect_similarity_signals always returns similarCount=0 for them.
    # Count how many other reviews share the exact same cleaned text instead.
    # Applied to ALL short positive reviews (stars >= 4), not just those in
    # EMPTY_WORDS — closes the blind spot where bot rings spam a short phrase
    # not in the dictionary (e.g. "服務態度超好" × 50). See Issue #53.
    short_exact_counts = [0] * len(reviews)
    cleaned_texts = []
    is_short_positive = []
    for r in reviews:
        text = r.get('text', '') or ''
        try:
            stars = int(r.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        cleaned = STRIP_PUNCT_RE.sub('', text)
        cleaned_texts.append(cleaned)
        is_short_positive.append(
            stars >= 4 and 0 < len(cleaned) <= config.min_template_chars
        )

    # Build frequency map of cleaned texts among short positive reviews
    short_text_freq = defaultdict(int)
    for i, is_short in enumerate(is_short_positive):
        if is_short:
            short_text_freq[cleaned_texts[i]] += 1
    for i, is_short in enumerate(is_short_positive):
        if is_short:
            short_exact_counts[i] = short_text_freq[cleaned_texts[i]] - 1  # exclude self

    # Whistleblower detection: ≤3-star reviews mentioning incentive keywords
    # are customers exposing wash behavior, not participants.  Count them as a
    # store-level signal (Issue #77).
    whistleblower_indices = set()
    for i, review in enumerate(reviews):
        text = (review.get('text', '') or '').strip()
        if not text:
            continue
        try:
            stars = int(review.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        if stars <= 3 and _check_incentive_semantic(text):
            whistleblower_indices.add(i)

    # Ratio of no-text 5-star reviews for escalation
    total_reviews = len(reviews)
    no_text_5star_count = sum(
        1 for r in reviews
        if not (r.get('text', '') or '').strip()
        and int(r.get('stars') or 0) == 5
    )
    no_text_5star_ratio = no_text_5star_count / total_reviews if total_reviews > 0 else 0

    # Per-review audit
    audited = []
    for i, review in enumerate(reviews):
        is_spike = spike_flags[i]
        sim_count = max(similar_counts[i], short_exact_counts[i])

        audit = audit_review(review, {
            'isSpikePeriod': is_spike,
            'similarCount': sim_count,
            'noTextRatio': no_text_5star_ratio,
        }, config)

        # Override: hard duplicate detection (only for 4+ stars — low-star
        # duplicates are complaints, not wash campaigns)
        try:
            stars = int(review.get('stars') or 0)
        except (ValueError, TypeError):
            stars = 0
        if not audit['isWashed'] and template_flags[i] and stars >= 4:
            audit = {
                'isWashed': True,
                'reason': '⚠️ 檢測到此評論內文與店內其他評論相似度大於 75%，高度疑似模板洗評。',
                'confidenceScore': 90,
                'issueType': 'template',
            }

        # Rule 2.6: structural template — only for ambiguous reviews (issueType=null)
        if audit['issueType'] is None:
            struct_sig = {
                'maxSimilarity': max_similarity[i],
                'similarCount': sim_count,
                'hotTermCount': hot_term_counts[i],
                'hotTermMaxRatio': hot_term_max_ratios[i],
            }
            if hits_structural_template(struct_sig, config):
                confidence = compute_structural_confidence(
                    sim_count, hot_term_max_ratios[i], nearby_long_review_counts[i],
                )
                reasons = []
                if max_similarity[i] >= config.structural_min_similarity and sim_count >= config.structural_min_similar_count:
                    reasons.append(f'與店內 {sim_count} 則評論結構相似（最高相似度 {max_similarity[i]:.0%}）')
                if hot_term_counts[i] >= config.structural_min_hot_term_count and hot_term_max_ratios[i] >= config.structural_min_hot_term_ratio:
                    reasons.append(f'反覆使用全店高頻詞組（占比 {hot_term_max_ratios[i]:.0%}）')
                audit = {
                    'isWashed': True,
                    'reason': '⚠️ ' + '；'.join(reasons),
                    'confidenceScore': confidence,
                    'issueType': 'template',
                    'verdictBasis': 'structural',
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

    # Build whistleblower details list
    whistleblower_reviews = []
    for i in sorted(whistleblower_indices):
        r = reviews[i]
        whistleblower_reviews.append({
            'username': r.get('username', ''),
            'text': r.get('text', ''),
            'stars': int(r.get('stars') or 0),
        })

    return {
        'auditedReviews': audited,
        'signals': {
            'similarity': similarity_signals,
            'hotTerm': hot_term_signals,
            'nearbyLongReviewCounts': nearby_long_review_counts,
            'spikeMonths': sorted(spike_months),
            'noTextRatio': no_text_ratio,
            'foreignLanguageRatio': foreign_language_ratio,
            'whistleblowerCount': len(whistleblower_indices),
            'whistleblowerReviews': whistleblower_reviews,
        },
    }
