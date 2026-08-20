"""
Tests for the canonical Stage 1 rule engine (review_scraper/rule_engine.py)
and the /api/audit-rules endpoint in server.py.
"""
import pytest
from rule_engine import (
    RuleConfig,
    audit_review,
    run_stage1_audit,
    detect_no_text_ratio,
    detect_language_ratio,
    detect_spike_months,
)


# ─── audit_review unit tests ───────────────────────────────

class TestAuditReview:
    def test_no_text_review(self):
        result = audit_review({'text': '', 'stars': 5})
        assert result['issueType'] == 'no_text'
        assert result['isWashed'] is False
        assert result['confidenceScore'] == 50

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
    def _make_reviews(self, month_counts):
        """Helper: generate reviews with given counts per month."""
        reviews = []
        for month, count in month_counts.items():
            for day in range(1, count + 1):
                d = min(day, 28)
                reviews.append({'stars': 5, 'time': f'{month}-{d:02d}', 'text': ''})
        return reviews

    def test_no_spike_uniform(self):
        """Uniform distribution should not trigger spike."""
        reviews = self._make_reviews({
            '2025-01': 15, '2025-02': 15, '2025-03': 15, '2025-04': 15,
        })
        _, spike_months = detect_spike_months(reviews)
        assert spike_months == set()

    def test_spike_at_3x(self):
        """A month with >3x average and >=10 should be flagged."""
        reviews = self._make_reviews({
            '2025-01': 10, '2025-02': 10, '2025-03': 10, '2025-04': 40,
        })
        # avg = 17.5, 3x = 52.5 → 40 is NOT a spike
        _, spike_months = detect_spike_months(reviews)
        assert '2025-04' not in spike_months

    def test_spike_just_under_3x(self):
        """A month just under 3x average should NOT be flagged."""
        reviews = self._make_reviews({
            '2025-01': 10, '2025-02': 10, '2025-03': 10, '2025-04': 60,
        })
        # avg = 22.5, 3x = 67.5 → 60 is NOT a spike (just under)
        _, spike_months = detect_spike_months(reviews)
        assert '2025-04' not in spike_months

    def test_spike_clear_outlier(self):
        """A clear outlier (>3x) should be flagged."""
        reviews = self._make_reviews({
            '2025-01': 10, '2025-02': 10, '2025-03': 10, '2025-04': 100,
        })
        # avg = 32.5, 3x = 97.5 → 100 IS a spike
        _, spike_months = detect_spike_months(reviews)
        assert '2025-04' in spike_months

    def test_spike_below_min_count(self):
        """Even at >3x, months with <10 reviews should not spike."""
        reviews = self._make_reviews({
            '2025-01': 2, '2025-02': 2, '2025-03': 2, '2025-04': 9,
        })
        _, spike_months = detect_spike_months(reviews)
        assert spike_months == set()

    def test_old_2x_would_have_spiked(self):
        """Verify that the old 2x threshold would flag this but 3x doesn't."""
        reviews = self._make_reviews({
            '2025-01': 10, '2025-02': 10, '2025-03': 10, '2025-04': 30,
        })
        # avg = 15, 2x = 30 → would spike at 2x; 3x = 45 → no spike at 3x
        _, spike_months = detect_spike_months(reviews)
        assert '2025-04' not in spike_months

    def test_config_override(self):
        """Custom config can loosen or tighten spike detection."""
        reviews = self._make_reviews({
            '2025-01': 10, '2025-02': 10, '2025-03': 10, '2025-04': 31,
        })
        # avg = 15.25, 2x = 30.5 → 31 > 30.5 → spike with 2x
        loose = RuleConfig(spike_multiplier=2.0)
        _, spike_months = detect_spike_months(reviews, loose)
        assert '2025-04' in spike_months
