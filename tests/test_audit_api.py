import pytest

import server


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def make_review(i, text="好吃，老闆人很好，推薦"):
    return {"username": f"user{i}", "stars": 5, "text": text, "daysElapsed": i, "isSpikePeriod": False}


def fake_llm_scores(batch):
    """Return IAD-only score items matching the new LLM output schema."""
    return [
        {
            "id": idx,
            "reasoning": "測試推理過程",
            "incentiveIntensity": 1,
            "sentimentAuthenticity": 5,
            "descriptionGranularity": 5,
        }
        for idx in range(len(batch))
    ]


def test_audit_returns_results_for_each_review(client, monkeypatch):
    monkeypatch.setattr(server, "call_llm_batch", lambda provider, client_to_use, store_name, batch, **kwargs: fake_llm_scores(batch))
    # Bypass score cache
    monkeypatch.setattr(server, "get_cached_scores", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "set_cached_scores", lambda *args, **kwargs: None)

    reviews = [make_review(i) for i in range(5)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 5
    assert {item["username"] for item in data["results"]} == {f"user{i}" for i in range(5)}
    # Server now returns complete results with confidence
    for item in data["results"]:
        assert "confidenceScore" in item
        assert "isWashed" in item
        assert item["verdictBasis"] == "content"


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
    def raise_malformed(provider, client_to_use, store_name, batch, **kwargs):
        raise ValueError("Gemini 回傳內容非合法 JSON：模擬缺欄位/格式錯誤")

    monkeypatch.setattr(server, "call_llm_batch", raise_malformed)
    monkeypatch.setattr(server, "get_cached_scores", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "set_cached_scores", lambda *args, **kwargs: None)

    reviews = [make_review(i) for i in range(3)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    # All batches failed -> a clean 5xx JSON error
    assert resp.status_code >= 400
    data = resp.get_json()
    assert "error" in data


def test_audit_partial_batch_failure_still_returns_successful_results(client, monkeypatch):
    call_count = {"n": 0}

    def sometimes_failing(provider, client_to_use, store_name, batch, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("模擬第一批失敗")
        return fake_llm_scores(batch)

    monkeypatch.setattr(server, "call_llm_batch", sometimes_failing)
    monkeypatch.setattr(server, "make_batches", lambda reviews: [reviews[:1], reviews[1:]])
    monkeypatch.setattr(server, "get_cached_scores", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "set_cached_scores", lambda *args, **kwargs: None)

    reviews = [make_review(i) for i in range(2)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    data = resp.get_json()
    # 1 batch succeeded (1 review scored) + 1 batch failed (1 review unscored)
    scored = [r for r in data["results"] if r.get("stage2") != "unscored"]
    assert len(scored) >= 1
    assert "errors" in data and len(data["errors"]) == 1


def test_audit_splits_100_reviews_into_multiple_batches(client, monkeypatch):
    seen_batch_sizes = []

    def recording(provider, client_to_use, store_name, batch, **kwargs):
        seen_batch_sizes.append(len(batch))
        return fake_llm_scores(batch)

    monkeypatch.setattr(server, "call_llm_batch", recording)
    monkeypatch.setattr(server, "get_cached_scores", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "set_cached_scores", lambda *args, **kwargs: None)

    reviews = [make_review(i) for i in range(100)]
    resp = client.post("/api/audit", json={"storeName": "測試店家", "reviews": reviews})

    assert resp.status_code == 200
    assert len(seen_batch_sizes) > 1
    assert sum(seen_batch_sizes) == 100
    assert all(size <= 50 for size in seen_batch_sizes)


def test_audit_api_key_validation(client, monkeypatch):
    monkeypatch.setattr(server, "call_llm_batch", lambda provider, client_to_use, store_name, batch, **kwargs: fake_llm_scores(batch))
    monkeypatch.setattr(server, "get_cached_scores", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "set_cached_scores", lambda *args, **kwargs: None)
    reviews = [make_review(0)]

    # 1. Valid API key (starts with AIzaSy and is >= 35 chars)
    valid_key = "AIzaSy" + "A" * 30
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": valid_key}
    )
    assert resp.status_code == 200

    # 2. Invalid API key prefix
    invalid_prefix = "AIzaXy" + "A" * 30
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": invalid_prefix}
    )
    assert resp.status_code == 400

    # 3. Too short API key
    too_short = "AIzaSy" + "A" * 20
    resp = client.post(
        "/api/audit",
        json={"storeName": "測試", "reviews": reviews},
        headers={"X-Gemini-API-Key": too_short}
    )
    assert resp.status_code == 400
