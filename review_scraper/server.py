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
from cache_store import get_cached_reviews, set_cached_reviews, get_place_id_for_query, set_query_place_id_mapping
from rule_engine import run_stage1_audit
import re

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

app = Flask(__name__)
CORS(app)

@app.route("/", methods=["GET"])
def index():
    logger.info(f"Root path '/' accessed by IP: {request.remote_addr}")
    return jsonify({
        "status": "ok",
        "message": "Google Maps Scraper Service is running"
    })

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
                logger.info(f"extract_place_id successfully found place_id '{place_id}' for URL: {url}")
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

    if not force and target_place_id:
        cached = get_cached_reviews(target_place_id)
        if cached is not None:
            logger.info(f"Cache hit for place_id: {target_place_id} ({len(cached)} reviews)")
            return jsonify({"reviews": cached, "source": "cache"})

    try:
        # Imported lazily: apify_scraper pulls in the Apify HTTP client, which
        # the rest of this app (notably /api/audit and its tests) doesn't need.
        from apify_scraper import scrape_via_apify, NotARestaurantError

        logger.info(f"Starting Apify scrape for URL: {url_to_scrape} (limit: {max_reviews})")
        apify_place_id, records = scrape_via_apify(url_to_scrape, max_reviews=max_reviews)
        
        final_place_id = apify_place_id or target_place_id
        if final_place_id:
            set_cached_reviews(final_place_id, records, source="apify")
            # Always save mapping if it was a query or if we resolved a place_id
            set_query_place_id_mapping(original_query, final_place_id)
            if is_url and url_to_scrape != original_query:
                set_query_place_id_mapping(url_to_scrape, final_place_id)
        
        logger.info(f"Apify scrape succeeded: {len(records)} reviews in {time.time() - start_time:.2f}s.")
        return jsonify({"reviews": records, "source": "apify"})
    except NotARestaurantError as e:
        logger.info(f"Not a restaurant, rejecting: {url} — {e}")
        return jsonify({"error": str(e)}), 400
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
    if not raw_reviews or not isinstance(raw_reviews, list):
        logger.error(f"audit-rules request from {ip} failed validation: Missing or invalid field 'reviews'")
        return jsonify({"error": "Missing or invalid required field: reviews"}), 400

    normalized = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        normalized.append(normalize_review(r))

    if not normalized:
        return jsonify({"auditedReviews": [], "signals": {"similarity": [], "hotTerm": [], "nearbyLongReviewCounts": [], "spikeMonths": []}})

    result = run_stage1_audit(normalized)
    logger.info(f"audit-rules completed: {len(result['auditedReviews'])} reviews in {time.time() - start_time:.2f}s.")
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
    logger.info("Initializing Flask server configurations...")
    logger.info("Starting Flask server on host 0.0.0.0, port 5001...")
    app.run(host="0.0.0.0", port=5001)
