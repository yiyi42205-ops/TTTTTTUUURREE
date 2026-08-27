import pytest

import apify_scraper
import cache_store
import server


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def isolated_cache_db(tmp_path, monkeypatch):
    """Every test gets a fresh temp SQLite file instead of touching the real
    project-root cache.db. DB_PATH is read at call time (not bound as a
    default-argument value), so monkeypatching the module attribute works.
    Also sets a fake APIFY_TOKEN so integration tests reach the scraper code
    path (the server checks for a token before calling scrape_via_apify)."""
    db_path = str(tmp_path / "test_cache.db")
    monkeypatch.setattr(cache_store, "DB_PATH", db_path)
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    yield db_path


# ---- Fakes for the apify_client.ApifyClient chain: client.actor(id).call(...), client.dataset(id).list_items().items ----

class FakeRun:
    """Mirrors the real apify_client Run object: a plain attribute-bearing
    object (actually a Pydantic BaseModel) — NOT a dict. There is deliberately
    no .get() method here: apify_scraper.py used to call run.get("status") /
    run.get("defaultDatasetId") and crash with AttributeError even when the
    Apify run itself succeeded. Every test below exercises this object shape
    so that regression can't sneak back in."""

    def __init__(self, status, default_dataset_id):
        self.status = status
        self.default_dataset_id = default_dataset_id


class FakeActorClient:
    def __init__(self, run_result):
        self._run_result = run_result
        self.call_kwargs = None

    def call(self, **kwargs):
        self.call_kwargs = kwargs
        return self._run_result


class FakeListItemsResult:
    def __init__(self, items):
        self.items = items


class FakeDatasetClient:
    def __init__(self, items):
        self._items = items

    def list_items(self, **kwargs):
        return FakeListItemsResult(self._items)


class FakeApifyClient:
    def __init__(self, token, run_result=None, dataset_items=None):
        self.token = token
        self._actor_client = FakeActorClient(
            run_result if run_result is not None else FakeRun("SUCCEEDED", "fake-dataset")
        )
        self._dataset_client = FakeDatasetClient(dataset_items or [])

    def actor(self, actor_id):
        self.last_actor_id = actor_id
        return self._actor_client

    def dataset(self, dataset_id):
        self.last_dataset_id = dataset_id
        return self._dataset_client


def make_fake_client_factory(**kwargs):
    def factory(token):
        return FakeApifyClient(token, **kwargs)
    return factory


# ---- scrape_via_apify() unit tests ----

def test_scrape_via_apify_normalizes_results(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "fake-token")
    dataset_items = [
        {"name": "Alice", "stars": 5, "text": "好吃 老闆很親切", "publishedAtDate": "2025-01-01", "reviewImageUrls": ["a.jpg", "b.jpg"], "placeId": "ChIJ_test123"},
        {"name": "Bob", "stars": 4, "text": None, "textTranslated": "Great food", "placeId": "ChIJ_test123"},
    ]
    monkeypatch.setattr(apify_scraper, "ApifyClient", make_fake_client_factory(dataset_items=dataset_items))

    place_id, results, metadata = apify_scraper.scrape_via_apify("https://maps.google.com/?cid=123", max_reviews=10)

    assert place_id == "ChIJ_test123"
    assert len(results) == 2
    assert results[0]["username"] == "Alice"
    assert results[0]["stars"] == 5
    assert results[0]["hasText"] is True
    assert results[0]["imageCount"] == 2
    assert results[1]["username"] == "Bob"
    assert results[1]["text"] == "Great food"  # falls back to textTranslated when text is None
    assert results[1]["hasText"] is True
    assert metadata == {}  # no totalScore in test data


def test_scrape_via_apify_returns_metadata(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "fake-token")
    dataset_items = [
        {"name": "Alice", "stars": 5, "text": "好吃", "placeId": "ChIJ_meta", "totalScore": 3.9, "reviewsCount": 500},
    ]
    monkeypatch.setattr(apify_scraper, "ApifyClient", make_fake_client_factory(dataset_items=dataset_items))
    place_id, results, metadata = apify_scraper.scrape_via_apify("https://maps.google.com/?cid=456", max_reviews=10)
    assert metadata["totalScore"] == 3.9
    assert metadata["reviewsCount"] == 500


def test_scrape_via_apify_raises_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="APIFY_TOKEN"):
        apify_scraper.scrape_via_apify("https://maps.google.com/?cid=123")


def test_scrape_via_apify_raises_when_run_not_succeeded(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "fake-token")
    monkeypatch.setattr(
        apify_scraper, "ApifyClient",
        make_fake_client_factory(run_result=FakeRun("FAILED", "x")),
    )
    with pytest.raises(RuntimeError, match="FAILED"):
        apify_scraper.scrape_via_apify("https://maps.google.com/?cid=123")


def test_scrape_via_apify_reads_run_via_attributes_not_dict_get(monkeypatch):
    """Regression test for a real bug: the Apify run completed successfully
    (actor logs showed 50 reviews scraped), but scrape_via_apify still raised
    "'Run' object has no attribute 'get'" because it accessed run.get(...)
    instead of run.status / run.default_dataset_id. FakeRun above has no
    .get() method at all, so this would fail loudly if that regressed."""
    monkeypatch.setenv("APIFY_TOKEN", "fake-token")
    dataset_items = [{"name": "Alice", "stars": 5, "text": "好吃", "placeId": "ChIJ_999"}]
    monkeypatch.setattr(
        apify_scraper, "ApifyClient",
        make_fake_client_factory(run_result=FakeRun("SUCCEEDED", "fake-dataset"), dataset_items=dataset_items),
    )

    place_id, results, metadata = apify_scraper.scrape_via_apify("https://maps.google.com/?cid=999", max_reviews=10)

    assert place_id == "ChIJ_999"
    assert len(results) == 1
    assert results[0]["username"] == "Alice"


# ---- /api/scrape primary(Apify)/fallback(Playwright)/cache integration tests ----

def fake_playwright_dataframe(records):
    import pandas as pd
    return pd.DataFrame(records)


def test_scrape_uses_apify_when_it_succeeds(client, monkeypatch):
    def fake_scrape_via_apify(url, max_reviews=50, token=None):
        return "ChIJ_1", [{"username": "u1", "stars": 5, "time": "2025-01-01", "text": "讚", "images": [], "hasText": True, "imageCount": 0}], {}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape_via_apify)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=1", "maxReviews": 10})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "apify"
    assert len(data["reviews"]) == 1


def test_scrape_does_not_fall_back_to_playwright_by_default(client, monkeypatch):
    """Playwright fallback is opt-in: with ENABLE_PLAYWRIGHT_FALLBACK unset,
    an Apify failure must return the Apify error directly, and Playwright
    must never even be invoked."""
    monkeypatch.delenv("ENABLE_PLAYWRIGHT_FALLBACK", raising=False)

    def failing_apify(url, max_reviews=50, token=None):
        raise RuntimeError("Apify token 無效")

    playwright_called = {"called": False}

    def fake_playwright(url, max_reviews=50):
        playwright_called["called"] = True
        return fake_playwright_dataframe([{"Username": "should-not-be-used", "Stars": 5, "Text": "x"}])

    monkeypatch.setattr("apify_scraper.scrape_via_apify", failing_apify)
    monkeypatch.setattr("scraper.scrape_google_maps_reviews", fake_playwright)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=2", "maxReviews": 10})
    assert resp.status_code == 500
    assert "Apify token 無效" in resp.get_json()["error"]
    assert playwright_called["called"] is False


def test_scrape_falls_back_to_playwright_when_apify_fails_and_fallback_enabled(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PLAYWRIGHT_FALLBACK", "true")

    def failing_apify(url, max_reviews=50, token=None):
        raise RuntimeError("Apify token 無效")

    def fake_playwright(url, max_reviews=50):
        return fake_playwright_dataframe([
            {"Username": "u2", "Stars": 4, "Time": "2025-02-01", "Text": "不錯", "Images": ""}
        ])

    monkeypatch.setattr("apify_scraper.scrape_via_apify", failing_apify)
    monkeypatch.setattr("scraper.scrape_google_maps_reviews", fake_playwright)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=2b", "maxReviews": 10})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "playwright_fallback"
    assert data["reviews"][0]["username"] == "u2"


def test_scrape_returns_500_when_both_apify_and_playwright_fail_and_fallback_enabled(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PLAYWRIGHT_FALLBACK", "true")

    def failing_apify(url, max_reviews=50, token=None):
        raise RuntimeError("Apify 額度用盡")

    def failing_playwright(url, max_reviews=50):
        raise RuntimeError("Playwright 也失敗了")

    monkeypatch.setattr("apify_scraper.scrape_via_apify", failing_apify)
    monkeypatch.setattr("scraper.scrape_google_maps_reviews", failing_playwright)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=3"})
    assert resp.status_code == 500
    assert "error" in resp.get_json()


def test_scrape_cache_hit_skips_apify(client, monkeypatch):
    call_count = {"n": 0}

    def counting_apify(url, max_reviews=50, token=None):
        call_count["n"] += 1
        return "ChIJ_4", [{"username": "fresh", "stars": 5, "time": "2025-01-01", "text": "讚", "images": [], "hasText": True, "imageCount": 0}], {}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", counting_apify)

    url = "https://maps.google.com/?cid=4"
    first = client.post("/api/scrape", json={"url": url})
    assert first.get_json()["source"] == "apify"
    # First request: probe (1 review, cache miss) + full scrape = 2 calls
    assert call_count["n"] == 2

    second = client.post("/api/scrape", json={"url": url})
    assert second.get_json()["source"] == "cache"
    assert second.get_json()["reviews"][0]["username"] == "fresh"
    assert call_count["n"] == 2  # Apify was not called again


def test_scrape_force_true_bypasses_cache(client, monkeypatch):
    call_count = {"n": 0}

    def counting_apify(url, max_reviews=50, token=None):
        call_count["n"] += 1
        return "ChIJ_5", [{"username": f"user{call_count['n']}", "stars": 5, "time": "2025-01-01", "text": "讚", "images": [], "hasText": True, "imageCount": 0}], {}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", counting_apify)

    url = "https://maps.google.com/?cid=5"
    client.post("/api/scrape", json={"url": url})
    # First request: probe + full scrape = 2 calls
    assert call_count["n"] == 2

    # force=true skips cache check and probe, does full scrape then merges
    resp = client.post("/api/scrape?force=true", json={"url": url})
    assert resp.get_json()["source"] == "merged"
    assert call_count["n"] == 3


def test_scrape_merges_new_reviews_into_cache(client, monkeypatch):
    """Apify returns some overlapping + some new reviews. The merge should
    keep all cached reviews, update overlapping ones, and add new ones."""
    cached_reviews = [
        {"username": f"u{i}", "stars": 5, "time": "2025-01-01", "text": "好吃", "images": [], "hasText": True, "imageCount": 0}
        for i in range(100)
    ]
    # Apify returns 3 reviews: u0 (overlap, updated text), u1 (overlap), new_user (new)
    apify_reviews = [
        {"username": "u0", "stars": 4, "time": "2025-06-01", "text": "改評價了", "images": [], "hasText": True, "imageCount": 0},
        {"username": "u1", "stars": 5, "time": "2025-01-01", "text": "好吃", "images": [], "hasText": True, "imageCount": 0},
        {"username": "new_user", "stars": 3, "time": "2025-06-15", "text": "普通", "images": [], "hasText": True, "imageCount": 0},
    ]

    call_count = {"n": 0}

    def apify_varying(url, max_reviews=50, token=None):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return "ChIJ_merge", cached_reviews, {"totalScore": 3.9, "reviewsCount": 500}
        return "ChIJ_merge", apify_reviews, {"totalScore": 4.0, "reviewsCount": 510}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", apify_varying)

    url = "https://maps.google.com/?cid=merge"

    # First call: seeds cache with 100 reviews
    first = client.post("/api/scrape", json={"url": url})
    assert len(first.get_json()["reviews"]) == 100

    # Second call with force=true: Apify returns 3 (2 overlap + 1 new) → merge
    second = client.post("/api/scrape?force=true", json={"url": url})
    data = second.get_json()
    assert data["source"] == "merged"
    assert len(data["reviews"]) == 101  # 100 + 1 new
    # u0 should be updated to Apify's version
    u0 = next(r for r in data["reviews"] if r["username"] == "u0")
    assert u0["text"] == "改評價了"
    assert u0["stars"] == 4
    # new_user should be present
    assert any(r["username"] == "new_user" for r in data["reviews"])
    assert data["metadata"]["totalScore"] == 4.0


def test_scrape_probe_hits_cache_avoids_full_scrape(client, monkeypatch):
    """When a user pastes a URL without ChIJ, the probe discovers the place_id
    and finds pre-crawled data in cache — no full scrape needed."""
    import cache_store

    # Pre-seed cache with 500 reviews (simulating pre-crawled data)
    pre_crawled = [
        {"username": f"u{i}", "stars": 5, "time": "2025-01-01", "text": "好吃", "images": [], "hasText": True, "imageCount": 0}
        for i in range(500)
    ]
    cache_store.set_cached_reviews("ChIJ_precrawled", pre_crawled, source="playwright_batch")

    call_count = {"n": 0}

    def probe_only_apify(url, max_reviews=50, token=None):
        call_count["n"] += 1
        return "ChIJ_precrawled", [{"username": "probe", "stars": 3, "time": "2025-06-01", "text": "x", "images": [], "hasText": True, "imageCount": 0}], {"totalScore": 4.2}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", probe_only_apify)

    resp = client.post("/api/scrape", json={"url": "https://maps.app.goo.gl/someShortLink"})
    data = resp.get_json()
    assert data["source"] == "cache"
    assert len(data["reviews"]) == 500
    assert call_count["n"] == 1  # Only the probe, no full scrape


# ---- URL Normalization, Redirection & SSRF mitigation tests ----

def test_resolve_google_share_url_valid_redirect(monkeypatch):
    class FakeResponse:
        def __init__(self, url):
            self._url = url
        def geturl(self):
            return self._url
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    urlopen_calls = []
    def fake_urlopen(req, timeout=5):
        urlopen_calls.append(req)
        return FakeResponse("https://www.google.com/maps/place/SomeRestaurant")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resolved = server.resolve_google_share_url("https://share.google/abc")
    assert resolved == "https://www.google.com/maps/place/SomeRestaurant"
    assert len(urlopen_calls) == 1
    assert urlopen_calls[0].get_full_url() == "https://share.google/abc"
    assert urlopen_calls[0].method == "HEAD"


def test_resolve_google_share_url_ssrf_mitigation(monkeypatch):
    urlopen_calls = []
    def fake_urlopen(req, timeout=5):
        urlopen_calls.append(req)
        raise RuntimeError("Should not be called")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    # Hostname is evil.com, should bypass resolving and return original URL
    resolved = server.resolve_google_share_url("http://evil.com/share.google/xyz")
    assert resolved == "http://evil.com/share.google/xyz"
    assert len(urlopen_calls) == 0


def test_resolve_google_share_url_handles_exceptions(monkeypatch):
    def fake_urlopen(req, timeout=5):
        raise ValueError("Network issue")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    # Should catch exception and gracefully fallback to returning the original URL
    resolved = server.resolve_google_share_url("https://share.google/fail")
    assert resolved == "https://share.google/fail"


def test_scrape_normalizes_plain_text_query(client, monkeypatch):
    captured_url = []
    def fake_scrape_via_apify(url, max_reviews=50, token=None):
        captured_url.append(url)
        return "ChIJ_text", [{"username": "u1", "stars": 5, "time": "2025-01-01", "text": "讚", "images": [], "hasText": True, "imageCount": 0}], {}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape_via_apify)

    # Send plain text query that doesn't start with http/https
    resp = client.post("/api/scrape", json={"url": "蘇草salvia", "maxReviews": 10})
    assert resp.status_code == 200
    # probe + full scrape = 2 calls, both to the same normalized URL
    assert len(captured_url) == 2
    assert captured_url[0] == "https://www.google.com/maps/search/%E8%98%87%E8%8D%89salvia"
    assert captured_url[1] == captured_url[0]


def test_scrape_rejects_non_string_url(client):
    # Test with an integer url
    resp = client.post("/api/scrape", json={"url": 12345})
    assert resp.status_code == 400
    assert "must be a non-empty string" in resp.get_json()["error"]

    # Test with a dict url
    resp = client.post("/api/scrape", json={"url": {"not": "a string"}})
    assert resp.status_code == 400
    assert "must be a non-empty string" in resp.get_json()["error"]


def test_scrape_rejects_oversized_url(client):
    oversized_url = "https://www.google.com/maps/place/" + ("A" * 2050)
    resp = client.post("/api/scrape", json={"url": oversized_url})
    assert resp.status_code == 400
    assert "URL length exceeds limit" in resp.get_json()["error"]


# ---- Non-restaurant category gate ----

def test_scrape_rejects_non_restaurant_category(client, monkeypatch):
    """When Apify returns a non-food categoryName (e.g. 公園), the endpoint
    should return 400 with an appropriate error message."""
    def fake_scrape(url, max_reviews=50, token=None):
        return "ChIJ_park", [
            {"username": "u1", "stars": 5, "time": "2025-01-01", "text": "漂亮", "images": [], "hasText": True, "imageCount": 0},
        ], {"totalScore": 4.5, "categoryName": "公園"}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=park1"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "本系統僅適用於餐飲店家" in data["error"]
    assert "公園" in data["error"]


def test_scrape_allows_restaurant_category(client, monkeypatch):
    """A venue with a food-related categoryName should pass through normally."""
    def fake_scrape(url, max_reviews=50, token=None):
        return "ChIJ_rest", [
            {"username": "u1", "stars": 5, "time": "2025-01-01", "text": "好吃", "images": [], "hasText": True, "imageCount": 0},
        ], {"totalScore": 4.3, "categoryName": "餐廳"}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=rest1"})
    assert resp.status_code == 200
    assert len(resp.get_json()["reviews"]) == 1


def test_scrape_allows_missing_category(client, monkeypatch):
    """When no categoryName is present (e.g. Playwright fallback or old cache),
    the request should proceed without blocking."""
    def fake_scrape(url, max_reviews=50, token=None):
        return "ChIJ_nocat", [
            {"username": "u1", "stars": 4, "time": "2025-01-01", "text": "ok", "images": [], "hasText": True, "imageCount": 0},
        ], {"totalScore": 4.0}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape)

    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=nocat"})
    assert resp.status_code == 200


def test_scrape_probe_rejects_non_restaurant_before_full_scrape(client, monkeypatch):
    """The probe path should also reject non-restaurant venues early, before
    running a full (and costly) Apify scrape."""
    full_scrape_called = {"called": False}

    call_count = {"n": 0}
    def fake_scrape(url, max_reviews=50, token=None):
        call_count["n"] += 1
        if max_reviews == 1:
            # Probe — returns non-restaurant category
            return None, [], {"categoryName": "觀光景點"}
        full_scrape_called["called"] = True
        return "ChIJ_x", [
            {"username": "u1", "stars": 5, "time": "2025-01-01", "text": "讚", "images": [], "hasText": True, "imageCount": 0},
        ], {"categoryName": "觀光景點"}

    monkeypatch.setattr("apify_scraper.scrape_via_apify", fake_scrape)

    # Use a URL that won't match any cached place_id, forcing a probe
    resp = client.post("/api/scrape", json={"url": "https://maps.google.com/?cid=tourist1"})
    assert resp.status_code == 400
    assert "本系統僅適用於餐飲店家" in resp.get_json()["error"]
    assert not full_scrape_called["called"], "Full scrape should not run after probe rejects"


def test_is_food_category_helper():
    """Spot-check the _is_food_category helper for common categories."""
    from server import _is_food_category

    # Food venues
    assert _is_food_category("餐廳")
    assert _is_food_category("日本料理餐廳")
    assert _is_food_category("咖啡廳")
    assert _is_food_category("飲料店")
    assert _is_food_category("火鍋店")
    assert _is_food_category("Italian Restaurant")
    assert _is_food_category("Coffee shop")
    assert _is_food_category("Pizza place")
    assert _is_food_category("Bakery")
    assert _is_food_category("Bar")
    assert _is_food_category("素食餐廳")

    # Non-food venues
    assert not _is_food_category("公園")
    assert not _is_food_category("觀光景點")
    assert not _is_food_category("博物館")
    assert not _is_food_category("購物中心")
    assert not _is_food_category("旅館")
    assert not _is_food_category("Church")
    assert not _is_food_category("Museum")


