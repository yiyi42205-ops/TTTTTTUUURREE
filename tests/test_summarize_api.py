import pytest
from flask import json
from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_store_summary_golden_case(client, monkeypatch):
    import server

    fake_result = {
        "warnings": [
            {"summary": "有評論者提到排隊時間長", "sourceReviewIds": ["真實顧客"]},
            {"summary": "有評論者提到口味不如預期", "sourceReviewIds": ["真實顧客"]},
        ],
        "recommendations": [
            {"item": "厚切豬排定食", "reason": "炸豬排非常酥脆多汁，份量也很大", "sourceReviewIds": ["老饕"]},
        ],
    }
    monkeypatch.setattr(server, "call_llm_summary", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "set_cached_summary", lambda *args, **kwargs: None)

    payload = {
        "placeId": "ChIJ_test_golden",
        "storeName": "網紅排隊名店",
        "reviews": [
            {
                "id": "真實顧客",
                "username": "真實顧客",
                "stars": 1,
                "text": "排隊排了一個半小時，口味非常普通，完全不值那個價錢。",
            },
            {
                "id": "洗評仔",
                "username": "洗評仔",
                "stars": 5,
                "text": "好好吃讚讚讚",
                "audit": {"isWashed": True},
            },
            {
                "id": "老饕",
                "username": "老饕",
                "stars": 5,
                "text": "炸豬排非常酥脆多汁，份量也很大，強烈推薦他們的厚切豬排定食！",
            },
        ],
    }

    response = client.post("/api/store-summary", json=payload)
    assert response.status_code == 200, f"API failed: {response.get_json()}"

    data = response.get_json()
    assert "warnings" in data
    assert "recommendations" in data

    # Washed review should not appear in results
    all_ids = []
    for w in data["warnings"]:
        all_ids.extend(w.get("sourceReviewIds", []))
    for r in data["recommendations"]:
        all_ids.extend(r.get("sourceReviewIds", []))
    assert "洗評仔" not in all_ids, "Washed review leaked into summary"

    # Should have warnings and recommendations
    assert len(data["warnings"]) >= 1
    assert len(data["recommendations"]) >= 1


def test_store_summary_cache_hit(client, monkeypatch):
    import server

    cached = {
        "warnings": [{"summary": "cached warning", "sourceReviewIds": ["u1"]}],
        "recommendations": [],
    }
    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: cached)

    payload = {
        "placeId": "ChIJ_cached",
        "storeName": "快取店",
        "reviews": [{"text": "test", "stars": 5}],
    }

    response = client.post("/api/store-summary", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["warnings"][0]["summary"] == "cached warning"


def test_store_summary_missing_place_id(client):
    response = client.post("/api/store-summary", json={"reviews": [{"text": "test"}]})
    assert response.status_code == 400
    assert response.get_json()["code"] == "VALIDATION_ERROR"


def test_store_summary_no_valid_reviews(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: None)

    payload = {
        "placeId": "ChIJ_empty",
        "storeName": "空評論店",
        "reviews": [
            {"text": "", "stars": 5},
            {"text": "washed", "stars": 5, "audit": {"isWashed": True}},
        ],
    }

    response = client.post("/api/store-summary", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["warnings"] == []
    assert data["recommendations"] == []


def test_store_summary_missing_reviews(client):
    response = client.post("/api/store-summary", json={"placeId": "ChIJ_test"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "VALIDATION_ERROR"


def test_store_summary_llm_failure(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "set_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "call_llm_summary", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API down")))

    payload = {
        "placeId": "ChIJ_fail",
        "storeName": "失敗店",
        "reviews": [{"text": "好吃的拉麵", "stars": 5}],
    }

    response = client.post("/api/store-summary", json=payload)
    assert response.status_code == 502
    assert response.get_json()["code"] == "LLM_FAILED"


def test_store_summary_filters_washed_reviews(client, monkeypatch):
    import server

    captured_reviews = []
    def fake_summary(provider, client, store_name, reviews, **kwargs):
        captured_reviews.extend(reviews)
        return {"warnings": [], "recommendations": []}

    monkeypatch.setattr(server, "get_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "set_cached_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "call_llm_summary", fake_summary)

    payload = {
        "placeId": "ChIJ_filter",
        "storeName": "過濾測試店",
        "reviews": [
            {"text": "真的好吃", "stars": 4, "username": "clean_user"},
            {"text": "好吃讚", "stars": 5, "username": "washed_user", "audit": {"isWashed": True}},
            {"text": "", "stars": 5, "username": "empty_user"},
        ],
    }

    response = client.post("/api/store-summary", json=payload)
    assert response.status_code == 200
    assert len(captured_reviews) == 1
    assert captured_reviews[0].get("username") == "clean_user"
