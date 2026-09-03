"""
Tests for the canonical Stage 1 rule engine (review_scraper/rule_engine.py)
and the /api/audit-rules endpoint in server.py.
"""
import pytest
from datetime import datetime
from langdetect import DetectorFactory
DetectorFactory.seed = 0
from rule_engine import (
    RuleConfig,
    audit_review,
    run_stage1_audit,
    detect_no_text_ratio,
    detect_language_ratio,
    detect_spike_months,
    hits_structural_template,
    compute_structural_confidence,
)


# ─── audit_review unit tests ───────────────────────────────

class TestAuditReview:
    def test_no_text_review(self):
        result = audit_review({'text': '', 'stars': 5})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 85

    def test_no_text_5star_spike_escalation(self):
        """Blank 5-star review during spike → washed."""
        result = audit_review({'text': '', 'stars': 5}, context={'isSpikePeriod': True})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is True
        assert result['confidenceScore'] == 75

    def test_no_text_5star_high_ratio_escalation(self):
        """Blank 5-star review when no-text 5-star ratio >= 20% → washed."""
        result = audit_review({'text': '', 'stars': 5}, context={'noTextRatio': 0.25})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is True
        assert result['confidenceScore'] == 75

    def test_no_text_5star_low_ratio_no_escalation(self):
        """Blank 5-star review with low no-text ratio → not washed."""
        result = audit_review({'text': '', 'stars': 5}, context={'noTextRatio': 0.10})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 85

    def test_no_text_4star_spike_no_escalation(self):
        """Blank 4-star review during spike → NOT escalated (only 5-star)."""
        result = audit_review({'text': '', 'stars': 4}, context={'isSpikePeriod': True})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 85

    def test_no_text_confidence_lower_than_low_info(self):
        """no_text escalated (75) should be less confident than low_info escalated (85),
        because '好吃' is more suspicious than blank."""
        no_text = audit_review({'text': '', 'stars': 5}, context={'isSpikePeriod': True})
        low_info = audit_review({'text': '好吃', 'stars': 5}, context={'isSpikePeriod': True})
        assert no_text['confidenceScore'] < low_info['confidenceScore']

    def test_incentive_keyword(self):
        result = audit_review({'text': '打卡送飲料很開心', 'stars': 5})
        assert result['issueType'] == 'incentive'
        assert result['isWashed'] is True
        assert result['confidenceScore'] == 100

    def test_send_context_with_promo(self):
        """'送' with a promo keyword and no excludes → incentive."""
        result = audit_review({'text': '分享貼文送甜點', 'stars': 5})
        assert result['issueType'] == 'incentive'
        assert result['isWashed'] is True

    def test_send_context_excluded(self):
        """'送' in a delivery context (外送) should NOT trigger incentive."""
        result = audit_review({'text': '外送速度很快，餐點完整', 'stars': 5})
        assert result['issueType'] is None
        assert result['isWashed'] is False

    def test_low_info_no_escalation(self):
        result = audit_review({'text': '好吃', 'stars': 5}, context={})
        assert result['issueType'] == 'low_info'
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 55

    def test_low_info_escalated_by_spike(self):
        result = audit_review(
            {'text': '好吃', 'stars': 5},
            context={'isSpikePeriod': True, 'similarCount': 0},
        )
        assert result['issueType'] == 'template'
        assert result['isWashed'] is True
        assert result['confidenceScore'] == 85

    def test_low_info_escalated_by_similarity(self):
        result = audit_review(
            {'text': '推推', 'stars': 5},
            context={'isSpikePeriod': False, 'similarCount': 3},
        )
        assert result['issueType'] == 'template'
        assert result['isWashed'] is True

    def test_ambiguous_review_sent_to_stage2(self):
        result = audit_review({
            'text': '今天來吃了義大利麵，味道不錯，服務也很好，下次會再來。',
            'stars': 5,
        })
        assert result['issueType'] is None
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 80

    def test_low_star_short_review_not_low_info(self):
        """Low stars (< 4) should NOT be flagged as low_info even if text is short."""
        result = audit_review({'text': '好吃', 'stars': 2})
        assert result['issueType'] is None


# ─── run_stage1_audit integration tests ─────────────────────

class TestRunStage1Audit:
    def test_empty_reviews(self):
        result = run_stage1_audit([])
        assert result['auditedReviews'] == []
        assert result['signals']['similarity'] == []

    def test_basic_audit_flow(self):
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '東西好吃，環境也不錯，值得推薦。'},
            {'username': 'b', 'stars': 5, 'time': '2025-01-02', 'text': '打卡送飲料'},
        ]
        result = run_stage1_audit(reviews)
        assert len(result['auditedReviews']) == 2
        assert result['auditedReviews'][1]['audit']['issueType'] == 'incentive'
        assert 'similarity' in result['signals']
        assert 'spikeMonths' in result['signals']

    def test_duplicate_override(self):
        """Hard duplicate detection should override a non-washed audit."""
        text = '這家店的牛肉麵真的超級好吃，湯頭濃郁，麵條Q彈，牛肉軟嫩入味，推薦大家來吃。'
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': text},
            {'username': 'b', 'stars': 5, 'time': '2025-01-02', 'text': text},
        ]
        result = run_stage1_audit(reviews)
        for r in result['auditedReviews']:
            assert r['audit']['isWashed'] is True
            assert r['audit']['issueType'] == 'template'
            assert r['audit']['confidenceScore'] == 90

    def test_low_star_duplicate_not_washed(self):
        """Low-star duplicates are complaints, not wash campaigns."""
        text = '這家店的牛肉麵真的超級難吃，湯頭油膩，麵條爛掉，牛肉硬到咬不動，千萬不要來。'
        reviews = [
            {'username': 'a', 'stars': 1, 'time': '2025-01-01', 'text': text},
            {'username': 'b', 'stars': 2, 'time': '2025-01-02', 'text': text},
        ]
        result = run_stage1_audit(reviews)
        for r in result['auditedReviews']:
            assert r['audit']['isWashed'] is False

    def test_signals_structure(self):
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '好吃'},
        ]
        result = run_stage1_audit(reviews)
        signals = result['signals']
        assert len(signals['similarity']) == 1
        assert 'isDuplicate' in signals['similarity'][0]
        assert 'maxSimilarity' in signals['similarity'][0]
        assert 'similarCount' in signals['similarity'][0]
        assert len(signals['hotTerm']) == 1
        assert 'hotTermCount' in signals['hotTerm'][0]
        assert 'hotTermMaxRatio' in signals['hotTerm'][0]
        assert len(signals['nearbyLongReviewCounts']) == 1
        assert isinstance(signals['spikeMonths'], list)


# ─── /api/audit-rules endpoint tests ────────────────────────

@pytest.fixture
def client():
    from server import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


class TestAuditRulesEndpoint:
    def test_happy_path(self, client):
        resp = client.post('/api/audit-rules', json={
            'reviews': [
                {'username': 'test', 'stars': 5, 'time': '2025-03-01', 'text': '好吃又便宜，推薦大家來試試看。'},
            ],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'auditedReviews' in data
        assert 'signals' in data
        assert len(data['auditedReviews']) == 1

    def test_empty_reviews_returns_400(self, client):
        resp = client.post('/api/audit-rules', json={'reviews': []})
        assert resp.status_code == 400

    def test_missing_reviews_returns_400(self, client):
        resp = client.post('/api/audit-rules', json={})
        assert resp.status_code == 400

    def test_incentive_detection(self, client):
        resp = client.post('/api/audit-rules', json={
            'reviews': [
                {'username': 'u1', 'stars': 5, 'time': '2025-01-01', 'text': '打卡送飲料，很開心'},
            ],
        })
        data = resp.get_json()
        assert data['auditedReviews'][0]['audit']['issueType'] == 'incentive'
        assert data['auditedReviews'][0]['audit']['isWashed'] is True

    def test_signals_returned(self, client):
        resp = client.post('/api/audit-rules', json={
            'reviews': [
                {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '餐點不錯'},
                {'username': 'b', 'stars': 4, 'time': '2025-01-02', 'text': '還可以'},
            ],
        })
        data = resp.get_json()
        signals = data['signals']
        assert len(signals['similarity']) == 2
        assert len(signals['hotTerm']) == 2
        assert len(signals['nearbyLongReviewCounts']) == 2
        assert isinstance(signals['spikeMonths'], list)

    def test_duplicate_detection(self, client):
        text = '這家店的黑蒜油豚骨拉麵非常好吃，湯頭濃郁順口，叉燒軟嫩多汁，強力推薦大家來試試。'
        resp = client.post('/api/audit-rules', json={
            'reviews': [
                {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': text},
                {'username': 'b', 'stars': 5, 'time': '2025-01-02', 'text': text},
            ],
        })
        data = resp.get_json()
        for r in data['auditedReviews']:
            assert r['audit']['isWashed'] is True
            assert r['audit']['issueType'] == 'template'


# ─── No-text ratio signal (Issue #9) ──────────────────────────

class TestNoTextRatio:
    def test_all_have_text(self):
        reviews = [
            {'text': '好吃', 'stars': 5},
            {'text': '不錯', 'stars': 4},
        ]
        assert detect_no_text_ratio(reviews) == 0.0

    def test_mixed(self):
        reviews = [
            {'text': '好吃', 'stars': 5},
            {'text': '', 'stars': 5},
            {'text': '  ', 'stars': 5},
            {'text': '推薦', 'stars': 5},
        ]
        assert detect_no_text_ratio(reviews) == 0.5

    def test_all_empty(self):
        reviews = [{'text': '', 'stars': 5}, {'text': '', 'stars': 5}]
        assert detect_no_text_ratio(reviews) == 1.0

    def test_empty_list(self):
        assert detect_no_text_ratio([]) == 0.0

    def test_in_signals_output(self):
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '好吃'},
            {'username': 'b', 'stars': 5, 'time': '2025-01-01', 'text': ''},
        ]
        result = run_stage1_audit(reviews)
        assert result['signals']['noTextRatio'] == 0.5


# ─── Language ratio signal (Issue #10) ─────────────────────────

class TestLanguageRatio:
    def test_all_chinese(self):
        reviews = [
            {'text': '今天來吃了拉麵，味道不錯', 'stars': 5},
            {'text': '環境很好，服務親切', 'stars': 5},
        ]
        assert detect_language_ratio(reviews) == 0.0

    def test_mixed_languages(self):
        reviews = [
            {'text': '好吃推薦大家來', 'stars': 5},
            {'text': 'Great food, highly recommended!', 'stars': 5},
        ]
        ratio = detect_language_ratio(reviews)
        assert ratio == 0.5

    def test_empty_reviews_excluded(self):
        reviews = [
            {'text': '', 'stars': 5},
            {'text': 'Delicious food', 'stars': 5},
        ]
        ratio = detect_language_ratio(reviews)
        # Only 1 text review, and it's English
        assert ratio == 1.0

    def test_empty_list(self):
        assert detect_language_ratio([]) == 0.0

    def test_in_signals_output(self):
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '好吃'},
        ]
        result = run_stage1_audit(reviews)
        assert 'foreignLanguageRatio' in result['signals']


# ─── Regression: Stage 1 verdicts must not be sent to Stage 2 ──

class TestStage1VerdictLock:
    """Issue #2: Stage 1 non-null issueType reviews must be excluded from
    the Stage 2 pool.  The frontend filters on ``issueType === null`` before
    sending to Gemini.  These tests verify that the rule engine's contract
    (non-null issueType ↔ Stage-1-final) holds for every category, so the
    frontend filter is safe to rely on."""

    MIXED_REVIEWS = [
        # incentive — Stage 1 final
        {'username': 'promo', 'stars': 5, 'time': '2025-01-01',
         'text': '打卡送小菜，好開心'},
        # no_text — Stage 1 final
        {'username': 'silent', 'stars': 5, 'time': '2025-01-01',
         'text': ''},
        # low_info — Stage 1 final (not escalated here, no spike/similarity)
        {'username': 'short', 'stars': 5, 'time': '2025-06-01',
         'text': '好吃'},
        # duplicate pair — Stage 1 final (template)
        {'username': 'dup_a', 'stars': 5, 'time': '2025-03-01',
         'text': '這家的招牌牛肉麵湯頭超濃郁，麵條Q彈有勁，牛肉大塊又軟嫩，CP值超高推薦。'},
        {'username': 'dup_b', 'stars': 5, 'time': '2025-03-02',
         'text': '這家的招牌牛肉麵湯頭超濃郁，麵條Q彈有勁，牛肉大塊又軟嫩，CP值超高推薦。'},
        # ambiguous — should be the ONLY one sent to Stage 2
        {'username': 'genuine', 'stars': 5, 'time': '2025-02-01',
         'text': '今天和朋友來慶生，點了松露燉飯和香煎鱸魚，燉飯味道濃郁但不膩，魚皮煎得很脆，整體體驗很棒。'},
    ]

    def test_stage1_final_reviews_have_non_null_issue_type(self):
        """Every Stage-1-decided review must have issueType != None."""
        result = run_stage1_audit(self.MIXED_REVIEWS)
        audited = result['auditedReviews']

        stage1_final = [r for r in audited if r['audit']['issueType'] is not None]
        # promo + silent + short + dup_a + dup_b = 5
        assert len(stage1_final) == 5

        expected = {
            'promo': 'incentive',
            'silent': 'no_text',
            'short': 'low_info',
            'dup_a': 'template',
            'dup_b': 'template',
        }
        for r in stage1_final:
            assert r['audit']['issueType'] == expected[r['username']], \
                f"{r['username']} expected {expected[r['username']]}, got {r['audit']['issueType']}"

    def test_only_ambiguous_reviews_eligible_for_stage2(self):
        """Only issueType=None reviews should enter the Stage 2 pool."""
        result = run_stage1_audit(self.MIXED_REVIEWS)
        audited = result['auditedReviews']

        stage2_pool = [r for r in audited if r['audit']['issueType'] is None]
        assert len(stage2_pool) == 1
        assert stage2_pool[0]['username'] == 'genuine'

    def test_stage1_verdict_is_deterministic(self):
        """Running the same reviews twice must produce identical verdicts."""
        result1 = run_stage1_audit(self.MIXED_REVIEWS)
        result2 = run_stage1_audit(self.MIXED_REVIEWS)

        for r1, r2 in zip(result1['auditedReviews'], result2['auditedReviews']):
            assert r1['audit'] == r2['audit'], \
                f"Non-deterministic verdict for {r1['username']}: {r1['audit']} vs {r2['audit']}"


# ─── Spike detection (threshold tuning) ──────────────────────

class TestSpikeDetection:
    @staticmethod
    def _make_reviews_spread(spans):
        """Helper: generate reviews spread evenly across date ranges.

        *spans* is a list of (start_date_str, count, days) tuples.
        Reviews are spread 1 per day over *days* days starting from start_date.
        """
        from datetime import timedelta
        reviews = []  # noqa: E501
        for start_str, count, days in spans:
            start = datetime.strptime(start_str, '%Y-%m-%d')
            for i in range(count):
                d = start + timedelta(days=int(i * days / max(count, 1)))
                reviews.append({'stars': 5, 'time': d.strftime('%Y-%m-%d'), 'text': ''})
        return reviews

    def test_no_spike_uniform(self):
        """Uniform density should not trigger spike."""
        # 4 months, ~15 reviews each, evenly spread → no spike
        reviews = self._make_reviews_spread([
            ('2025-01-01', 15, 30),
            ('2025-02-01', 15, 28),
            ('2025-03-01', 15, 31),
            ('2025-04-01', 15, 30),
        ])
        _, spike_months = detect_spike_months(reviews)
        assert spike_months == set()

    def test_spike_burst_in_few_days(self):
        """20 reviews crammed into 3 days among months of normal activity → spike."""
        reviews = self._make_reviews_spread([
            ('2025-01-01', 10, 30),  # ~1 review every 3 days
            ('2025-02-01', 10, 28),
            ('2025-03-01', 10, 31),
            ('2025-04-10', 20, 3),   # 20 reviews in 3 days = burst
        ])
        flags, spike_months = detect_spike_months(reviews)
        assert '2025-04' in spike_months
        assert sum(flags) >= 15  # most of the burst flagged

    def test_no_spike_moderate_increase(self):
        """Moderate increase spread over a full month is NOT a spike."""
        # 10/month for 3 months, then 25 over 30 days → density ~0.83/day
        # overall ~55/120 ≈ 0.46/day → 1.8× → below 3×
        reviews = self._make_reviews_spread([
            ('2025-01-01', 10, 30),
            ('2025-02-01', 10, 28),
            ('2025-03-01', 10, 31),
            ('2025-04-01', 25, 30),
        ])
        _, spike_months = detect_spike_months(reviews)
        assert spike_months == set()

    def test_spike_below_min_count(self):
        """Too few total reviews should never trigger spike."""
        reviews = self._make_reviews_spread([
            ('2025-01-01', 3, 30),
            ('2025-02-01', 3, 28),
            ('2025-04-10', 3, 1),
        ])
        _, spike_months = detect_spike_months(reviews)
        assert spike_months == set()

    def test_spike_same_day_cluster(self):
        """Many reviews on the same day → definite spike."""
        reviews = self._make_reviews_spread([
            ('2025-01-01', 10, 30),
            ('2025-02-01', 10, 28),
            ('2025-03-01', 10, 31),
        ])
        # Add 20 reviews all on the same day
        for _ in range(20):
            reviews.append({'stars': 5, 'time': '2025-04-15', 'text': ''})
        flags, spike_months = detect_spike_months(reviews)
        assert '2025-04' in spike_months

    def test_config_override(self):
        """Custom multiplier can loosen spike detection."""
        # Moderate burst: 20 reviews in 7 days among steady background
        # overall ~50/120 ≈ 0.42/day, burst window = 20/7 ≈ 2.86/day → 6.8×
        # At 3× → spike; at 10× → no spike
        reviews = self._make_reviews_spread([
            ('2025-01-01', 10, 30),
            ('2025-02-01', 10, 28),
            ('2025-03-01', 10, 31),
            ('2025-04-10', 20, 7),
        ])
        _, spike_months_default = detect_spike_months(reviews)
        assert '2025-04' in spike_months_default

        strict = RuleConfig(spike_multiplier=10.0)
        _, spike_months_strict = detect_spike_months(reviews, strict)
        assert spike_months_strict == set()


# ─── Structural template detection (rule 2.6) ─────────────────

class TestHitsStructuralTemplate:
    def test_similarity_hit(self):
        sig = {'maxSimilarity': 0.60, 'similarCount': 3, 'hotTermCount': 0, 'hotTermMaxRatio': 0.0}
        assert hits_structural_template(sig) is True

    def test_hot_term_hit(self):
        sig = {'maxSimilarity': 0.20, 'similarCount': 0, 'hotTermCount': 2, 'hotTermMaxRatio': 0.35}
        assert hits_structural_template(sig) is True

    def test_both_hit(self):
        sig = {'maxSimilarity': 0.60, 'similarCount': 3, 'hotTermCount': 3, 'hotTermMaxRatio': 0.5}
        assert hits_structural_template(sig) is True

    def test_neither_hit(self):
        sig = {'maxSimilarity': 0.40, 'similarCount': 1, 'hotTermCount': 1, 'hotTermMaxRatio': 0.1}
        assert hits_structural_template(sig) is False

    def test_similarity_just_below_threshold(self):
        sig = {'maxSimilarity': 0.54, 'similarCount': 2, 'hotTermCount': 0, 'hotTermMaxRatio': 0.0}
        assert hits_structural_template(sig) is False

    def test_similar_count_below_threshold(self):
        sig = {'maxSimilarity': 0.60, 'similarCount': 1, 'hotTermCount': 0, 'hotTermMaxRatio': 0.0}
        assert hits_structural_template(sig) is False

    def test_hot_term_count_below_threshold(self):
        sig = {'maxSimilarity': 0.0, 'similarCount': 0, 'hotTermCount': 1, 'hotTermMaxRatio': 0.5}
        assert hits_structural_template(sig) is False

    def test_hot_term_ratio_below_threshold(self):
        sig = {'maxSimilarity': 0.0, 'similarCount': 0, 'hotTermCount': 2, 'hotTermMaxRatio': 0.29}
        assert hits_structural_template(sig) is False


class TestComputeStructuralConfidence:
    def test_minimum(self):
        """All signals at zero → minimum confidence (60)."""
        assert compute_structural_confidence(0, 0.0, 0) == 60

    def test_maximum(self):
        """All signals at or above cap → maximum confidence (95)."""
        assert compute_structural_confidence(5, 1.0, 5) == 95

    def test_above_cap(self):
        """Values above cap should still be capped at 95."""
        assert compute_structural_confidence(10, 2.0, 10) == 95

    def test_partial(self):
        """similarCount=2, hotTermMaxRatio=0.3, nearby=0 → partial composite."""
        # composite = 0.4*(2/5) + 0.4*(0.3) + 0.2*(0/5) = 0.4*0.4 + 0.4*0.3 = 0.16+0.12 = 0.28
        # confidence = 60 + 0.28 * 35 = 60 + 9.8 = 69.8 → 70
        assert compute_structural_confidence(2, 0.3, 0) == 70

    def test_matches_typescript(self):
        """Cross-check with auditEngine.ts structural branch values."""
        # similarCount=3, hotTermMaxRatio=0.5, nearby=2
        # composite = 0.4*(3/5) + 0.4*(0.5) + 0.2*(2/5) = 0.24+0.20+0.08 = 0.52
        # confidence = 60 + 0.52*35 = 60 + 18.2 = 78.2 → 78
        assert compute_structural_confidence(3, 0.5, 2) == 78


class TestStructuralTemplateInStage1:
    """Integration: rule 2.6 in run_stage1_audit catches structural templates."""

    def _make_similar_reviews(self, n=10):
        """Generate reviews with high structural similarity and shared phrases."""
        # Template-like reviews: same opening + closing, minor middle variation.
        # 3-gram Jaccard should be high among these; shared 4+ char phrases
        # ("招牌豚骨拉麵", "湯頭濃郁順口") repeat across ≥ 3 reviews.
        base_texts = [
            '招牌豚骨拉麵湯頭濃郁順口，叉燒軟嫩，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，麵條Q彈，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，溏心蛋好吃，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，份量十足，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，CP值超高，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，配菜豐富，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，很有日本味，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，小菜也棒，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，環境乾淨，推薦必吃！',
            '招牌豚骨拉麵湯頭濃郁順口，服務親切，推薦必吃！',
        ]
        reviews = []
        for i in range(n):
            reviews.append({
                'username': f'user_{i}',
                'stars': 5,
                'time': f'2025-03-{(i % 28) + 1:02d}T12:{i:02d}:00',
                'text': base_texts[i % len(base_texts)],
            })
        return reviews

    def test_structural_template_caught_in_stage1(self):
        reviews = self._make_similar_reviews(10)
        result = run_stage1_audit(reviews)
        structural_hits = [
            r for r in result['auditedReviews']
            if r['audit'].get('verdictBasis') == 'structural'
        ]
        assert len(structural_hits) > 0
        for r in structural_hits:
            assert r['audit']['isWashed'] is True
            assert r['audit']['issueType'] == 'template'
            assert 60 <= r['audit']['confidenceScore'] <= 95

    def test_structural_template_not_sent_to_stage2(self):
        """Reviews caught by rule 2.6 should have issueType='template', not None."""
        reviews = self._make_similar_reviews(10)
        result = run_stage1_audit(reviews)
        for r in result['auditedReviews']:
            if r['audit'].get('verdictBasis') == 'structural':
                assert r['audit']['issueType'] == 'template'

    def test_low_signal_reviews_not_caught(self):
        """Reviews with low similarity/hotTerm should remain ambiguous."""
        reviews = [
            {'username': 'a', 'stars': 5, 'time': '2025-01-01', 'text': '今天第一次來，點了松露燉飯，味道超級棒，會再來！'},
            {'username': 'b', 'stars': 5, 'time': '2025-02-15', 'text': '朋友推薦的咖啡廳，拿鐵很好喝，蛋糕也好吃。'},
            {'username': 'c', 'stars': 5, 'time': '2025-03-10', 'text': '帶小孩來吃早午餐，兒童餐份量夠，環境乾淨。'},
        ]
        result = run_stage1_audit(reviews)
        for r in result['auditedReviews']:
            assert r['audit'].get('verdictBasis') != 'structural'


# ─── Whistleblower signal (Issue #77) ───────────────────────────

class TestWhistleblowerSignal:
    def test_low_star_incentive_counted_as_whistleblower(self):
        """≤3 star reviews mentioning incentive keywords should be counted."""
        reviews = [
            {'username': 'wb1', 'stars': 2, 'time': '2025-01-01',
             'text': '打卡送飲料才來的吧，東西超難吃'},
            {'username': 'wb2', 'stars': 1, 'time': '2025-01-02',
             'text': '五星好評送小菜，難怪評價這麼高'},
            {'username': 'normal', 'stars': 4, 'time': '2025-01-03',
             'text': '今天點了牛肉麵，味道不錯，環境乾淨舒適。'},
        ]
        result = run_stage1_audit(reviews)
        signals = result['signals']
        assert signals['whistleblowerCount'] == 2
        assert len(signals['whistleblowerReviews']) == 2
        usernames = {r['username'] for r in signals['whistleblowerReviews']}
        assert usernames == {'wb1', 'wb2'}

    def test_high_star_incentive_not_counted(self):
        """4-5 star reviews with incentive keywords are wash participants,
        not whistleblowers."""
        reviews = [
            {'username': 'washer', 'stars': 5, 'time': '2025-01-01',
             'text': '打卡送飲料，好開心！'},
            {'username': 'normal', 'stars': 4, 'time': '2025-01-02',
             'text': '餐點普通'},
        ]
        result = run_stage1_audit(reviews)
        assert result['signals']['whistleblowerCount'] == 0

    def test_no_text_review_not_counted(self):
        """Empty reviews should never be whistleblowers."""
        reviews = [
            {'username': 'silent', 'stars': 1, 'time': '2025-01-01', 'text': ''},
        ]
        result = run_stage1_audit(reviews)
        assert result['signals']['whistleblowerCount'] == 0

    def test_empty_reviews_whistleblower_zero(self):
        """Empty review list should return whistleblowerCount=0."""
        result = run_stage1_audit([])
        assert result['signals']['whistleblowerCount'] == 0
        assert result['signals']['whistleblowerReviews'] == []

    def test_whistleblower_reviews_contain_details(self):
        """Each whistleblower entry should have username, text, stars."""
        reviews = [
            {'username': 'reporter', 'stars': 2, 'time': '2025-01-01',
             'text': '打卡送飲料的店，食物普通'},
        ]
        result = run_stage1_audit(reviews)
        wb = result['signals']['whistleblowerReviews'][0]
        assert wb['username'] == 'reporter'
        assert wb['stars'] == 2
        assert '打卡' in wb['text']
