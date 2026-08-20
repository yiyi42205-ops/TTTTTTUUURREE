from __future__ import annotations

from flask import Flask, request, jsonify
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google import genai
import logging
import os
import time
import traceback
import urllib.request
from urllib.parse import urlparse

from normalize import normalize_review
from gemini_client import make_batches, call_gemini_batch, MAX_CONCURRENT_BATCHES
from cache_store import get_cached_reviews, set_cached_reviews, get_place_id_for_query, set_query_place_id_mapping, get_cached_audit, set_cached_audit, get_cached_metadata
from rule_engine import run_stage1_audit
import re

# categoryName keywords that indicate a food/drink venue.  If Apify returns a
# categoryName that contains none of these tokens, we treat the place as a
# non-restaurant venue and return an error instead of auditing.
_FOOD_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "餐廳", "餐館", "小吃", "飯店", "飯館", "食堂",
    "咖啡", "茶", "飲料", "飲品", "奶茶", "果汁", "酒吧", "酒館", "啤酒",
    "麵包", "烘焙", "蛋糕", "甜點", "甜品", "糕點", "冰淇淋", "冰品",
    "火鍋", "燒烤", "燒肉", "烤肉", "串燒", "鐵板燒",
    "壽司", "拉麵", "丼飯", "居酒屋", "日本料理", "日式",
    "披薩", "漢堡", "速食", "炸雞", "牛排",
    "素食", "蔬食", "早餐", "早午餐", "brunch",
    "buffet", "自助餐", "便當", "滷味", "鹹酥雞",
    "restaurant", "cafe", "coffee", "bakery", "bar",
    "food", "pizza", "burger", "noodle", "sushi",
    "bistro", "diner", "eatery", "grill", "pub",
    "dessert", "ice cream", "tea", "juice", "brewery",
)


def _is_food_category(category_name: str) -> bool:
    """Return True if *category_name* looks like a food/drink venue."""
    lower = category_name.lower()
    return any(kw in lower for kw in _FOOD_CATEGORY_KEYWORDS)

# Configure logging format and level
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger("ScraperServer")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "缺少 GEMINI_API_KEY 環境變數。請在專案根目錄建立 .env 檔案並設定 GEMINI_API_KEY"
        "（可參考 .env.example），或於啟動前以環境變數形式提供。"
    )

genai_client = genai.Client(api_key=GEMINI_API_KEY)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)

@app.route("/", methods=["GET"])
def index():
    # Serve the SPA frontend if dist/ exists, otherwise return API status
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return app.send_static_file("index.html")
    return jsonify({
        "status": "ok",
        "message": "Google Maps Scraper Service is running"
    })

@app.route("/<path:path>")
def catch_all(path):
    """Serve static files or fall back to index.html for SPA client-side routing."""
    static_file = os.path.join(STATIC_DIR, path)
    if os.path.exists(static_file) and not os.path.isdir(static_file):
        return app.send_static_file(path)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return app.send_static_file("index.html")
    return jsonify({"error": "Not found"}), 404

def resolve_google_share_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.hostname == "share.google":
            # Follow redirects using HEAD request with a standard browser User-Agent
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                final_url = response.geturl()
                logger.info(f"Resolved share.google URL {url} to: {final_url}")
                return final_url
    except Exception as e:
        logger.warning(f"Failed to resolve share.google URL {url}: {e}")
    return url

def extract_place_id(url: str) -> str | None:
    # Fast path: check URL string itself for ChIJ (e.g. query_place_id=ChIJxxx, or /place/...ChIJ)
    url_match = re.search(r'(ChIJ[\w-]+)', url)
    if url_match:
        place_id = url_match.group(1)
        logger.info(f"extract_place_id found place_id '{place_id}' in URL string: {url}")
        return place_id

    # Slow path: fetch the page HTML and search for ChIJ
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8', errors='ignore')
            match = re.search(r'(ChIJ[\w-]+)', html)
            if match:
                place_id = match.group(1)
                logger.info(f"extract_place_id found place_id '{place_id}' in HTML for URL: {url}")
                return place_id
            logger.info(f"extract_place_id found no place_id match for URL: {url}")
    except Exception as e:
        logger.warning(f"extract_place_id failed for URL {url}: {e}")
    return None

@app.route("/api/scrape", methods=["POST"])
def scrape():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/scrape request from IP: {ip}")
    
    data = request.get_json() or {}
    url = data.get("url")
    if not url or not isinstance(url, str):
        logger.error(f"Scrape request from {ip} failed validation: Missing or invalid field 'url'")
        return jsonify({"error": "Missing or invalid field: url (must be a non-empty string)"}), 400
    
    url = url.strip()
    if len(url) > 2048:
        logger.error(f"Scrape request from {ip} failed validation: URL length exceeds limit ({len(url)} > 2048)")
        return jsonify({"error": "URL length exceeds limit (max 2048 characters)"}), 400

    original_query = url
    is_url = original_query.startswith("http://") or original_query.startswith("https://")
    
    # 1. Fast path: check search_query_map first for O(1) lookup on EXACT match
    target_place_id = get_place_id_for_query(original_query)
    url_to_scrape = original_query

    # 2. If not found in mapping, try to extract or construct it
    if not target_place_id:
        if is_url:
            # First time seeing this URL. Resolve it and try to extract place_id via Regex
            url_to_scrape = resolve_google_share_url(original_query)
            target_place_id = extract_place_id(url_to_scrape)
        else:
            # Text query: No network extraction attempted. Apify will handle it.
            from urllib.parse import quote
            url_to_scrape = f"https://www.google.com/maps/search/{quote(original_query)}"
            logger.info(f"Converted text query to Google Maps search URL: {url_to_scrape}")
    else:
        # We know the place_id! For text queries, Apify still expects a search URL if cache expires.
        if not is_url:
            from urllib.parse import quote
            url_to_scrape = f"https://www.google.com/maps/search/{quote(original_query)}"
    
    max_reviews = data.get("maxReviews") or 50
    try:
        max_reviews = int(max_reviews)
    except ValueError:
        logger.warning(f"Invalid maxReviews value received: {data.get('maxReviews')}. Defaulting to 50.")
        max_reviews = 50

    force = request.args.get("force", "false").lower() == "true"

    # Helper: save all known query/URL → place_id mappings
    def _save_mappings(place_id):
        set_query_place_id_mapping(original_query, place_id)
        if is_url and url_to_scrape != original_query:
            set_query_place_id_mapping(url_to_scrape, place_id)

    if not force and target_place_id:
        cached = get_cached_reviews(target_place_id)
        if cached is not None:
            cached_meta = get_cached_metadata(target_place_id)
            logger.info(f"Cache hit for place_id: {target_place_id} ({len(cached)} reviews)")
            response = {"reviews": cached, "source": "cache"}
            if cached_meta:
                response["metadata"] = cached_meta
            return jsonify(response)

    try:
        from apify_scraper import scrape_via_apify

        # If we don't have a place_id yet, do a 1-review probe just to discover
        # it. Cost: ~$0.001. If the place_id matches a pre-crawled cache entry,
        # we skip the full scrape entirely.
        if not target_place_id and not force:
            logger.info(f"No place_id found, probing Apify with 1 review for: {url_to_scrape}")
            probe_place_id, _, probe_metadata = scrape_via_apify(url_to_scrape, max_reviews=1)

            # Early category gate: the 1-review probe already gives us
            # categoryName — reject non-restaurant venues before the full scrape.
            cat = (probe_metadata or {}).get("categoryName", "")
            if cat and not _is_food_category(cat):
                logger.info(f"Non-restaurant category detected via probe: '{cat}' for {url_to_scrape}")
                return jsonify({
                    "error": f"本系統僅適用於餐飲店家，偵測到此地點類別為「{cat}」，無法進行評論審計。"
                }), 400

            if probe_place_id:
                _save_mappings(probe_place_id)
                target_place_id = probe_place_id
                cached = get_cached_reviews(probe_place_id)
                if cached is not None:
                    if probe_metadata:
                        set_cached_reviews(probe_place_id, cached, source="cache", metadata=probe_metadata)
                    cached_meta = get_cached_metadata(probe_place_id)
                    logger.info(f"Probe found place_id {probe_place_id}, cache hit ({len(cached)} reviews)")
                    response = {"reviews": cached, "source": "cache"}
                    if cached_meta:
                        response["metadata"] = cached_meta
                    return jsonify(response)

        logger.info(f"Starting Apify scrape for URL: {url_to_scrape} (limit: {max_reviews})")
        apify_place_id, records, metadata = scrape_via_apify(url_to_scrape, max_reviews=max_reviews)

        # Category gate for full scrape (covers the path where we already had
        # a place_id and skipped the probe above).
        cat = (metadata or {}).get("categoryName", "")
        if cat and not _is_food_category(cat):
            logger.info(f"Non-restaurant category detected: '{cat}' for {url_to_scrape}")
            return jsonify({
                "error": f"本系統僅適用於餐飲店家，偵測到此地點類別為「{cat}」，無法進行評論審計。"
            }), 400

        final_place_id = apify_place_id or target_place_id
        if final_place_id:
            _save_mappings(final_place_id)

            # Merge with existing cache: deduplicate by username, prefer Apify's
            # newer version for existing users, add new users from both sides.
            existing = get_cached_reviews(final_place_id)
            if existing:
                by_username = {r["username"]: r for r in existing}
                for r in records:
                    by_username[r["username"]] = r  # Apify (newer) wins on conflict
                merged = list(by_username.values())
                new_count = len(merged) - len(existing)
                logger.info(f"Merged reviews for {final_place_id}: {len(existing)} cached + {len(records)} Apify → {len(merged)} total ({new_count} new)")
                set_cached_reviews(final_place_id, merged, source="merged", metadata=metadata)
                response = {"reviews": merged, "source": "merged"}
            else:
                set_cached_reviews(final_place_id, records, source="apify", metadata=metadata)
                response = {"reviews": records, "source": "apify"}
        else:
            response = {"reviews": records, "source": "apify"}

        logger.info(f"Apify scrape succeeded: {len(response['reviews'])} reviews in {time.time() - start_time:.2f}s.")
        if metadata:
            response["metadata"] = metadata
        return jsonify(response)
    except Exception as apify_err:
        logger.warning(f"Apify scrape failed for {url_to_scrape}: {apify_err}.")

        # Playwright fallback is opt-in: read at request time (not bound to a
        # module-level constant) so it can be toggled via env var / tests
        # without needing to reimport this module.
        fallback_enabled = os.getenv("ENABLE_PLAYWRIGHT_FALLBACK", "false").lower() == "true"
        if not fallback_enabled:
            logger.error(f"Playwright fallback disabled (set ENABLE_PLAYWRIGHT_FALLBACK=true to enable); returning Apify failure for {url_to_scrape}.")
            return jsonify({"error": str(apify_err)}), 500

        logger.warning("Falling back to Playwright.")
        try:
            # Imported lazily: scraper.py pulls in Playwright/pandas/BeautifulSoup,
            # which the rest of this app (notably /api/audit and its tests) doesn't need.
            from scraper import scrape_google_maps_reviews

            df = scrape_google_maps_reviews(url_to_scrape, max_reviews=max_reviews)
            records = [] if df.empty else [normalize_review(r) for r in df.to_dict(orient="records")]
            if target_place_id:
                set_cached_reviews(target_place_id, records, source="playwright_fallback")
                set_query_place_id_mapping(original_query, target_place_id)
                if is_url and url_to_scrape != original_query:
                    set_query_place_id_mapping(url_to_scrape, target_place_id)
            logger.info(f"Playwright fallback succeeded: {len(records)} reviews in {time.time() - start_time:.2f}s.")
            return jsonify({"reviews": records, "source": "playwright_fallback"})
        except Exception as playwright_err:
            logger.error(f"Both Apify and Playwright scraping failed for {url}.")
            logger.error(f"Apify error: {apify_err}")
            logger.error(f"Playwright error: {playwright_err}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(playwright_err)}), 500

@app.route("/api/audit-rules", methods=["POST"])
def audit_rules():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/audit-rules request from IP: {ip}")

    data = request.get_json() or {}
    raw_reviews = data.get("reviews")
    place_id = data.get("placeId")
    if not raw_reviews or not isinstance(raw_reviews, list):
        logger.error(f"audit-rules request from {ip} failed validation: Missing or invalid field 'reviews'")
        return jsonify({"error": "Missing or invalid required field: reviews"}), 400

    # Check audit cache
    if place_id:
        cached = get_cached_audit(place_id)
        if cached:
            logger.info(f"audit-rules cache hit for place_id: {place_id}")
            return jsonify(cached)

    normalized = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        normalized.append(normalize_review(r))

    if not normalized:
        return jsonify({"auditedReviews": [], "signals": {"similarity": [], "hotTerm": [], "nearbyLongReviewCounts": [], "spikeMonths": []}})

    result = run_stage1_audit(normalized)
    logger.info(f"audit-rules completed: {len(result['auditedReviews'])} reviews in {time.time() - start_time:.2f}s.")

    # Cache the result
    if place_id:
        set_cached_audit(place_id, result)

    return jsonify(result)


@app.route("/api/audit", methods=["POST"])
def audit():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/audit request from IP: {ip}")

    # Extract user-provided API key from headers if available
    user_api_key = request.headers.get("X-Gemini-API-Key")
    client_to_use = genai_client
    if user_api_key:
        user_api_key = user_api_key.strip()
        if not user_api_key.startswith("AIzaSy") or len(user_api_key) < 35:
            logger.warning(f"Invalid X-Gemini-API-Key format from IP: {ip}")
            return jsonify({"error": "無效的用戶 API Key 格式 (請確認長度與開頭)"}), 400

        try:
            client_to_use = genai.Client(api_key=user_api_key)
            logger.info("Using user-provided Gemini API Key for audit request.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client with user API key: {e}")
            return jsonify({"error": "無效的用戶 API Key 格式"}), 400

    data = request.get_json() or {}
    store_name = data.get("storeName") or "待審查店家"
    raw_reviews = data.get("reviews")
    if not raw_reviews or not isinstance(raw_reviews, list):
        logger.error(f"Audit request from {ip} failed validation: Missing or invalid required field 'reviews'")
        return jsonify({"error": "Missing or invalid required field: reviews"}), 400

    normalized = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        n = normalize_review(r)
        n["daysElapsed"] = r.get("daysElapsed", 0)
        n["isSpikePeriod"] = bool(r.get("isSpikePeriod", False))
        n["maxSimilarity"] = r.get("maxSimilarity", 0)
        n["similarCount"] = r.get("similarCount", 0)
        n["hotTermCount"] = r.get("hotTermCount", 0)
        n["hotTermMaxRatio"] = r.get("hotTermMaxRatio", 0)
        n["nearbyLongReviewCount"] = r.get("nearbyLongReviewCount", 0)
        normalized.append(n)

    if not normalized:
        return jsonify({"results": []})

    batches = make_batches(normalized)
    logger.info(f"Auditing {len(normalized)} reviews for '{store_name}' across {len(batches)} batch(es)...")

    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_BATCHES) as executor:
        futures = {executor.submit(call_gemini_batch, client_to_use, store_name, batch): batch for batch in batches}
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as e:
                logger.error(f"Gemini batch audit failed: {e}")
                logger.error(traceback.format_exc())
                errors.append(str(e))

    # Batches are independent LLM calls — one failing shouldn't discard results
    # from the batches that succeeded. Only fail the whole request if nothing came back.
    if errors and not results:
        return jsonify({"error": "Gemini 語意審計全部批次皆失敗", "details": errors}), 502

    logger.info(f"Audit completed: {len(results)} reviews classified, {len(errors)} batch failure(s), in {time.time() - start_time:.2f}s.")
    response_body = {"results": results}
    if errors:
        response_body["errors"] = errors
    return jsonify(response_body)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    logger.info("Initializing Flask server configurations...")
    logger.info(f"Starting Flask server on host 0.0.0.0, port {port}...")
    app.run(host="0.0.0.0", port=port)
