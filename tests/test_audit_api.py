import pytest

import server


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def make_review(i, text="好吃，老闆人很好，推薦"):
    return {"username": f"user{i}", "stars": 5, "text": text, "daysElapsed": i, "isSpikePeriod": False}


def fake_audit_items(batch):
    return [
        {
            "username": r["username"],
            "reasoningPath": "測試推理過程",
            "isWashed": False,
            "reason": "真實評論",
            "incentiveIntensity": 1,
            "sentimentAuthenticity": 5,
            "descriptionGranularity": 5,
            "issueType": "none",
        }
        for r in batch
    ]


def test_audit_returns_results_for_each_review(client, monkeypatch):
    monkeypatch.setattr(server, "call_gemini_batch", lambda genai_client, store_name, batch: fake_audit_items(batch))

    reviews = [make_review(i) for i in range(5)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 5
    assert {item["username"] for item in data["results"]} == {f"user{i}" for i in range(5)}


def test_audit_missing_reviews_field_returns_4xx():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        resp = c.post("/api/audit", json={"storeName": "測試店家"})
        assert 400 <= resp.status_code < 500
        assert "error" in resp.get_json()


def test_audit_non_list_reviews_field_returns_4xx(client):
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": "not-a-list"})
    assert 400 <= resp.status_code < 500


def test_audit_malformed_gemini_response_returns_error_not_crash(client, monkeypatch):
    def raise_malformed(genai_client, store_name, batch):
        raise ValueError("Gemini 回傳內容非合法 JSON：模擬缺欄位/格式錯誤")

    monkeypatch.setattr(server, "call_gemini_batch", raise_malformed)

    reviews = [make_review(i) for i in range(3)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    # All batches failed -> a clean 5xx JSON error, not an unhandled exception/500 traceback page.
    assert resp.status_code >= 400
    data = resp.get_json()
    assert "error" in data


def test_audit_partial_batch_failure_still_returns_successful_results(client, monkeypatch):
    call_count = {"n": 0}

    def sometimes_failing(genai_client, store_name, batch):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("模擬第一批失敗")
        return fake_audit_items(batch)

    monkeypatch.setattr(server, "call_gemini_batch", sometimes_failing)
    monkeypatch.setattr(server, "make_batches", lambda reviews: [reviews[:1], reviews[1:]])

    reviews = [make_review(i) for i in range(2)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 1
    assert "errors" in data and len(data["errors"]) == 1


def test_audit_splits_100_reviews_into_multiple_batches(client, monkeypatch):
    seen_batch_sizes = []

    def recording(genai_client, store_name, batch):
        seen_batch_sizes.append(len(batch))
        return fake_audit_items(batch)

    monkeypatch.setattr(server, "call_gemini_batch", recording)

    reviews = [make_review(i) for i in range(100)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    assert len(seen_batch_sizes) > 1
    assert sum(seen_batch_sizes) == 100
    assert all(size <= 50 for size in seen_batch_sizes)


def test_audit_api_key_validation(client, monkeypatch):
    monkeypatch.setattr(server, "call_gemini_batch", lambda genai_client, store_name, batch: fake_audit_items(batch))
    reviews = [make_review(0)]

    # 1. Valid API key (starts with AIzaSy and is >= 35 chars)
    valid_key = "AIzaSy" + "A" * 30
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": valid_key}
    )
    assert resp.status_code == 200

    # 2. Invalid API key prefix (starts with AIza but not AIzaSy)
    invalid_prefix = "AIzaXy" + "A" * 30
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": invalid_prefix}
    )
    assert resp.status_code == 400
    assert "無效的用戶 API Key 格式" in resp.get_json()["error"]

    # 3. Too short API key
    too_short = "AIzaSy" + "A" * 20
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": too_short}
    )
    assert resp.status_code == 400
    assert "無效的用戶 API Key 格式" in resp.get_json()["error"]

