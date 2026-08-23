import pytest
from flask import json
from server import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_summarize_golden_case(client):
    # This is an integration test hitting the real Gemini API.
    # We construct a payload mimicking the Golden Test Case described by the user.

    golden_review_id = "ChdDSUhNMG9nS0VJQ0FnSUNRMWVHT3F3RRAB"
    
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
            }
        ]
    }

    response = client.post("/api/summarize", json=payload)
    assert response.status_code == 200, f"API failed: {response.get_json()}"
    
    data = response.get_json()
    assert "warnings" in data
    assert "recommendations" in data
    
    warnings = data["warnings"]
    
    # 1. Fake review shouldn't appear in recommendations or warnings
    fake_id_found = any("FakeReviewId123" in tip.get("sourceReviewIds", []) for tip in warnings + data["recommendations"])
    assert not fake_id_found, "Washed reviews leaked into the summary!"
    
    # 2. Golden review should trigger specific warnings
    warning_texts = [w["summary"] for w in warnings]
    
    # The requirement says:
    # 產出的避雷提示中，至少要涵蓋「排隊時間長」與「口味／體驗不如預期」兩點
    has_queue_warning = any("排隊" in w or "等待" in w or "久" in w for w in warning_texts)
    has_taste_warning = any("口味" in w or "普通" in w or "不如預期" in w or "體驗" in w or "行銷" in w for w in warning_texts)
    
    assert has_queue_warning, f"Missing queue warning. Got: {warning_texts}"
    assert has_taste_warning, f"Missing taste warning. Got: {warning_texts}"
    
    # 3. Source ID must be attached
    golden_id_found = any(golden_review_id in w.get("sourceReviewIds", []) for w in warnings)
    assert golden_id_found, "Golden review ID was not attached to the warnings"
def test_gemini_client_summarize_robustness(monkeypatch):
    """
    Test the robust safeguards in call_gemini_summarize:
    1. Empty reviews are filtered out.
    2. Truncation to 150.
    3. Sorting by length.
    4. ID anonymization and mapping back.
    5. Hallucination prevention (dropping hallucinated IDs).
    """
    from gemini_client import call_gemini_summarize
    import json
    
    class FakeResponse:
        def __init__(self, text):
            self.text = text
            
    class FakeModels:
        def generate_content(self, model, contents, config):
            # Verify the prompt received anonymized IDs (R1, R2...)
            assert "RealLongId" not in contents
            assert "R1" in contents
            
            fake_json = {
                "warnings": [
                    {
                        "summary": "有評論者提到排隊很久",
                        "sourceReviewIds": ["R1", "R999"], # R999 is hallucinated
                        "supportCount": 1
                    },
                    {
                        "summary": "有評論者提到完全幻覺的警告",
                        "sourceReviewIds": ["R999"], # Fully hallucinated source
                        "supportCount": 1
                    }
                ],
                "recommendations": []
            }
            return FakeResponse(json.dumps(fake_json))
            
    class FakeClient:
        models = FakeModels()
        
    reviews = [
        {"id": "RealLongId_1", "text": "This is a very very long review text to test sorting.", "isWashed": False},
        {"id": "RealLongId_2", "text": "Short", "isWashed": False},
        {"id": "Washed_1", "text": "Fake", "isWashed": True},
        {"id": "Empty_1", "text": "", "isWashed": False},
        {"id": "Empty_2", "text": "   ", "isWashed": False}
    ]
    
    # Add 200 reviews to test truncation (150 max)
    for i in range(200):
        reviews.append({"id": f"Pad_{i}", "text": f"Pad {i}", "isWashed": False})
        
    result = call_gemini_summarize(FakeClient(), "TestStore", reviews)
    
    warnings = result["warnings"]
    
    # R1 should map back to RealLongId_1, because it's the longest text and sorted first.
    # The hallucinated warning with ONLY R999 should be entirely dropped.
    assert len(warnings) == 1, "Warning with completely hallucinated source should be dropped"
    
    mapped_ids = warnings[0]["sourceReviewIds"]
    assert "RealLongId_1" in mapped_ids, "R1 should map back to RealLongId_1"
    assert "R999" not in mapped_ids, "Hallucinated R999 should be filtered out"
    assert "R1" not in mapped_ids, "Short IDs should not leak to the final result"
