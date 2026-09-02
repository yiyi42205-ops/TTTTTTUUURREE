import pytest
import server
from conftest import TEST_GEMINI_KEY


class _GeminiClient:
    """Wraps Flask test client to auto-attach X-Gemini-API-Key header."""
    def __init__(self, inner):
        self._inner = inner

    def post(self, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("X-Gemini-API-Key", TEST_GEMINI_KEY)
        kwargs["headers"] = headers
        return self._inner.post(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield _GeminiClient(c)

def make_review(i, text="好吃，推薦"):
    return {"id": f"user{i}", "stars": 5, "text": text}

def fake_qa_result():
    return {
        "answer": "這家店的拉麵很有名。",
        "items": [{"id": "user1", "reason": "提到拉麵好吃"}],
        "sufficient": True
    }

def test_qa_returns_success(client, monkeypatch):
    # Mock LLM call to return fake result
    monkeypatch.setattr(server, "call_llm_qa", lambda *args, **kwargs: fake_qa_result())
    # Bypass cache and rate limit
    monkeypatch.setattr(server, "get_cached_qa", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "check_and_increment_qa_limit", lambda *args, **kwargs: True)
    monkeypatch.setattr(server, "set_cached_qa", lambda *args, **kwargs: None)

    reviews = [make_review(i) for i in range(5)]
    resp = client.post("/api/summarize", json={
        "placeId": "ChIJ_test",
        "storeName": "測試店家",
        "reviews": reviews,
        "question": "這家店推薦什麼？"
    })

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["answer"] == "這家店的拉麵很有名。"
    assert len(data["items"]) == 1

def test_qa_missing_question_returns_4xx(client):
    resp = client.post("/api/summarize", json={
        "placeId": "ChIJ_test",
        "storeName": "測試店家",
        "reviews": [make_review(1)]
    })
    assert resp.status_code == 400
    assert "Missing or invalid question" in resp.get_json()["error"]

def test_qa_question_too_long_returns_4xx(client):
    long_question = "A" * 501
    resp = client.post("/api/summarize", json={
        "placeId": "ChIJ_test",
        "storeName": "測試店家",
        "reviews": [make_review(1)],
        "question": long_question
    })
    assert resp.status_code == 400
    assert "字數超過上限" in resp.get_json()["error"]

def test_qa_rate_limit_exceeded_returns_429(client, monkeypatch):
    monkeypatch.setattr(server, "get_cached_qa", lambda *args, **kwargs: None)
    # Simulate rate limit exceeded
    monkeypatch.setattr(server, "check_and_increment_qa_limit", lambda *args, **kwargs: False)

    resp = client.post("/api/summarize", json={
        "placeId": "ChIJ_test",
        "storeName": "測試店家",
        "reviews": [make_review(1)],
        "question": "這家店推薦什麼？"
    })

    assert resp.status_code == 429

def test_qa_uses_cache_and_skips_llm(client, monkeypatch):
    llm_called = False
    def mock_llm(*args, **kwargs):
        nonlocal llm_called
        llm_called = True
        return fake_qa_result()

    monkeypatch.setattr(server, "call_llm_qa", mock_llm)
    # Simulate cache hit
    monkeypatch.setattr(server, "get_cached_qa", lambda *args, **kwargs: fake_qa_result())

    resp = client.post("/api/summarize", json={
        "placeId": "ChIJ_test",
        "storeName": "測試店家",
        "reviews": [make_review(1)],
        "question": "這家店推薦什麼？"
    })

    assert resp.status_code == 200
    assert not llm_called, "LLM should not be called if cache is hit"
    assert resp.get_json()["answer"] == "這家店的拉麵很有名。"
