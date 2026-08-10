"""
Tests for the canonical Stage 1 rule engine (review_scraper/rule_engine.py)
and the /api/audit-rules endpoint in server.py.
"""
import pytest
from rule_engine import (
    RuleConfig,
    audit_review,
    run_stage1_audit,
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
