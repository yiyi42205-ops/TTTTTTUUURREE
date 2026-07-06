from flask import Flask, request, jsonify
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google import genai
import logging
import os
import time
import traceback

from normalize import normalize_review
from gemini_client import make_batches, call_gemini_batch, MAX_CONCURRENT_BATCHES
from cache_store import get_cached_reviews, set_cached_reviews

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

@app.route("/api/scrape", methods=["POST"])
def scrape():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/scrape request from IP: {ip}")
    
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        logger.error(f"Scrape request from {ip} failed validation: Missing required field 'url'")
        return jsonify({"error": "Missing required field: url"}), 400
    
    max_reviews = data.get("maxReviews") or 50
    try:
        max_reviews = int(max_reviews)
    except ValueError:
        logger.warning(f"Invalid maxReviews value received: {data.get('maxReviews')}. Defaulting to 50.")
        max_reviews = 50

    force = request.args.get("force", "false").lower() == "true"

    if not force:
        cached = get_cached_reviews(url)
        if cached is not None:
            logger.info(f"Cache hit for URL: {url} ({len(cached)} reviews)")
            return jsonify({"reviews": cached, "source": "cache"})

    try:
        # Imported lazily: apify_scraper pulls in the Apify HTTP client, which
        # the rest of this app (notably /api/audit and its tests) doesn't need.
        from apify_scraper import scrape_via_apify

        logger.info(f"Starting Apify scrape for URL: {url} (limit: {max_reviews})")
        records = scrape_via_apify(url, max_reviews=max_reviews)
        set_cached_reviews(url, records, source="apify")
        logger.info(f"Apify scrape succeeded: {len(records)} reviews in {time.time() - start_time:.2f}s.")
        return jsonify({"reviews": records, "source": "apify"})
    except Exception as apify_err:
        logger.warning(f"Apify scrape failed for {url}: {apify_err}.")

        # Playwright fallback is opt-in: read at request time (not bound to a
        # module-level constant) so it can be toggled via env var / tests
        # without needing to reimport this module.
        fallback_enabled = os.getenv("ENABLE_PLAYWRIGHT_FALLBACK", "false").lower() == "true"
        if not fallback_enabled:
            logger.error(f"Playwright fallback disabled (set ENABLE_PLAYWRIGHT_FALLBACK=true to enable); returning Apify failure for {url}.")
            return jsonify({"error": str(apify_err)}), 500

        logger.warning("Falling back to Playwright.")
        try:
            # Imported lazily: scraper.py pulls in Playwright/pandas/BeautifulSoup,
            # which the rest of this app (notably /api/audit and its tests) doesn't need.
            from scraper import scrape_google_maps_reviews

            df = scrape_google_maps_reviews(url, max_reviews=max_reviews)
            records = [] if df.empty else [normalize_review(r) for r in df.to_dict(orient="records")]
            set_cached_reviews(url, records, source="playwright_fallback")
            logger.info(f"Playwright fallback succeeded: {len(records)} reviews in {time.time() - start_time:.2f}s.")
            return jsonify({"reviews": records, "source": "playwright_fallback"})
        except Exception as playwright_err:
            logger.error(f"Both Apify and Playwright scraping failed for {url}.")
            logger.error(f"Apify error: {apify_err}")
            logger.error(f"Playwright error: {playwright_err}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(playwright_err)}), 500

@app.route("/api/audit", methods=["POST"])
def audit():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/audit request from IP: {ip}")

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
        futures = {executor.submit(call_gemini_batch, genai_client, store_name, batch): batch for batch in batches}
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
