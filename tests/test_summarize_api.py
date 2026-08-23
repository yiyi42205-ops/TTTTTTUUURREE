import pytest
from flask import json
from server import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_summarize_golden_case(client, monkeypatch):
    import server

    # Mock the LLM call to return fake data instead of hitting the real API
    def fake_call_gemini_summarize(client_obj, store_name, reviews):
        return {
            "warnings": [
                {"summary": "有評論者提到排隊時間長", "sourceReviewIds": ["ChdDSUhNMG9nS0VJQ0FnSUNRMWVHT3F3RRAB"], "supportCount": 1},
                {"summary": "有評論者提到口味不如預期", "sourceReviewIds": ["ChdDSUhNMG9nS0VJQ0FnSUNRMWVHT3F3RRAB"], "supportCount": 1}
            ],
            "recommendations": [
                {"item": "厚切豬排定食", "reason": "炸豬排非常酥脆多汁，份量也很大", "sourceReviewIds": ["PosReview123"], "supportCount": 1}
            ]
        }
    monkeypatch.setattr(server, "call_gemini_summarize", fake_call_gemini_summarize)
    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "set_cached_summary", lambda *args, **kwargs: None)

    # This is an integration test hitting the real Gemini API.
    # We construct a payload mimicking the Golden Test Case described by the user.

    golden_review_id = "ChdDSUhNMG9nS0VJQ0FnSUNRMWVHT3F3RRAB"
    positive_review_id = "PosReview123"
    
    payload = {
        "mode": "single",
        "storeName": "網紅排隊名店 (Golden Test Store)",
        "reviews": [
            {
                "id": golden_review_id,
                "username": "真實顧客",
                "stars": 1,
                "text": "看了 IG 廣告跟網紅影片推薦才來的，結果大失所望。排隊排了一個半小時才進去，結果餐點送上來發現實際口味非常普通，完全不值那個價錢跟排隊的時間。高分根本都是靠行銷出來的。",
                "isWashed": False  # The engine judged it as genuine
            },
            {
                "id": "FakeReviewId123",
                "username": "洗評仔",
                "stars": 5,
                "text": "好好吃讚讚讚",
                "isWashed": True   # The engine caught this fake review
            },
            {
                "id": positive_review_id,
                "username": "老饕",
                "stars": 5,
                "text": "炸豬排非常酥脆多汁，份量也很大，強烈推薦他們的厚切豬排定食！",
                "isWashed": False  # Genuine positive review
            }
        ]
    }

    response = client.post("/api/summarize", json=payload)
    assert response.status_code == 200, f"API failed: {response.get_json()}"
    
    data = response.get_json()
    assert "warnings" in data
    assert "recommendations" in data
    
    warnings = data["warnings"]
    recommendations = data["recommendations"]
    
    # 1. Fake review shouldn't appear in recommendations or warnings
    fake_id_found = any("FakeReviewId123" in tip.get("sourceReviewIds", []) for tip in warnings + recommendations)
    assert not fake_id_found, "Washed reviews leaked into the summary!"
    
    # 2. Golden review should trigger specific warnings
    warning_texts = [w["summary"] for w in warnings]
    
    has_queue_warning = any("排隊" in w or "等待" in w or "久" in w for w in warning_texts)
    has_taste_warning = any("口味" in w or "普通" in w or "不如預期" in w or "體驗" in w or "行銷" in w for w in warning_texts)
    
    assert has_queue_warning, f"Missing queue warning. Got: {warning_texts}"
    assert has_taste_warning, f"Missing taste warning. Got: {warning_texts}"
    
    # 3. Source ID must be attached to warnings and single reviews must have correct prefix
    golden_id_found = any(golden_review_id in w.get("sourceReviewIds", []) for w in warnings)
    assert golden_id_found, "Golden review ID was not attached to the warnings"
    
    for w in warnings:
        if w.get("supportCount", 0) == 1:
            assert "有評論者提到" in w["summary"], f"Single review warning lacks prefix: {w['summary']}"
    
    # 4. Positive review should trigger recommendations
    rec_items = [r["item"] for r in recommendations]
    has_pork_chop_rec = any("豬排" in r for r in rec_items)
    assert has_pork_chop_rec, f"Missing pork chop recommendation. Got: {rec_items}"
    
    positive_id_found = any(positive_review_id in r.get("sourceReviewIds", []) for r in recommendations)
    assert positive_id_found, "Positive review ID was not attached to the recommendations"

