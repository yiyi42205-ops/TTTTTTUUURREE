from __future__ import annotations

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google import genai
import logging
import os
import time
import traceback
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from normalize import normalize_review
from llm_client import make_batches, call_llm_batch, MAX_CONCURRENT_BATCHES, call_llm_qa, call_llm_summary, MODEL_NAME_GEMINI, MODEL_NAME_DEEPSEEK, MODEL_NAME_OPENAI_COMPAT
from cache_store import (
    get_cached_reviews, set_cached_reviews, get_place_id_for_query,
    set_query_place_id_mapping, get_cached_audit, set_cached_audit, get_cached_metadata,
    check_and_increment_qa_limit, get_cached_qa, set_cached_qa,
    get_cached_summary, set_cached_summary,
    get_cached_scores, set_cached_scores,
    get_last_checked_at, set_last_checked_at, get_fetched_at,
    log_visitor, get_visitor_stats, update_cached_metadata,
)
from prompt_builder import get_prompt_version
from stage2_rules import build_stage2_result
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
# Lazy init: server can start without GEMINI_API_KEY (visitor mode only needs
# cache). The client is created on first use; /api/audit will return an error
# if no key is available (neither server-side nor user-provided).
genai_client = None
if GEMINI_API_KEY:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning(
        "GEMINI_API_KEY 未設定 — 伺服器仍可啟動（快取查詢正常），"
        "但 Stage 2 AI 審計需要用戶自帶 Gemini API Key。"
    )
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")

# Global DeepSeek Client
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
deepseek_client = None
if DEEPSEEK_API_KEY:
    try:
        import openai
        deepseek_client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    except ImportError:
        logger.warning("openai package not installed. DeepSeek backend will be unavailable.")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB request body limit

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").strip()
if _CORS_ORIGINS:
    CORS(app, origins=[o.strip() for o in _CORS_ORIGINS.split(",")])
else:
    CORS(app)  # dev fallback: allow all origins

# Rate limiter — per IP, in-memory storage (resets on deploy, fine for basic protection)
_limiter_enabled = os.getenv("TESTING") != "1"
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],
    storage_uri="memory://",
    enabled=_limiter_enabled,
)

# Background thread pool for incremental cache refresh (fire-and-forget)
_refresh_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache_refresh")

# How many seconds before a store can be re-checked (7 days)
REFRESH_COOLDOWN_SECONDS = 604800
# How many newest reviews to fetch for incremental refresh
REFRESH_REVIEW_COUNT = 20


def _background_refresh(place_id: str, url: str, apify_token: str) -> None:
    """Background task: fetch newest reviews from Apify, dedup, merge into cache.

    Called after a cache hit when the store hasn't been checked in 24+ hours.
    Updates last_checked_at unconditionally; updates fetched_at only when new
    reviews are actually found.
    """
    try:
        from apify_scraper import scrape_via_apify

        logger.info(f"[refresh] Starting incremental refresh for {place_id}")
        _, new_reviews, metadata = scrape_via_apify(
            url, max_reviews=REFRESH_REVIEW_COUNT, token=apify_token,
        )

        existing = get_cached_reviews(place_id)
        if not existing:
            # Shouldn't happen (we only refresh on cache hit), but guard anyway
            set_last_checked_at(place_id)
            return

        by_username = {r["username"]: r for r in existing}
        new_count = 0
        for r in new_reviews:
            if r["username"] not in by_username:
                new_count += 1
            by_username[r["username"]] = r  # newer version wins

        if new_count > 0:
            # New reviews first (from this refresh), then existing in original order.
            # Since Apify returns newest-first, this preserves recency ordering.
            seen = set()
            merged = []
            for r in list(new_reviews) + list(existing):
                u = r["username"]
                if u not in seen:
                    seen.add(u)
                    merged.append(by_username[u])  # use newest version
            # Cap at 500 reviews, dropping the oldest (tail)
            merged = merged[:500]
            logger.info(
                f"[refresh] {place_id}: {new_count} new reviews found, "
                f"merged {len(existing)} → {len(merged)}"
            )
            set_cached_reviews(place_id, merged, source="refresh", metadata=metadata)
            # set_cached_reviews already invalidates audit_cache
        else:
            logger.info(f"[refresh] {place_id}: no new reviews (all {len(new_reviews)} already cached)")

        # Always update last_checked_at (whether or not new reviews were found)
        set_last_checked_at(place_id)
    except Exception as e:
        logger.warning(f"[refresh] Background refresh failed for {place_id}: {e}")
        # Still mark as checked so we don't retry immediately on every request
        try:
            set_last_checked_at(place_id)
        except Exception:
            pass

def _resolve_llm_client(provider: str, headers: dict, ip: str) -> tuple[any, tuple[dict, int] | None]:
    """
    Factory helper to resolve the appropriate LLM client instance based on provider and headers.
    Returns: (client_instance, error_tuple_if_any)
    """
    if provider == "gemini":
        user_api_key = (headers.get("X-Gemini-API-Key") or "").strip()
        if not user_api_key:
            return None, ({"error": "AI 語意分析需要您的 Gemini API Key。請到 Google AI Studio 免費申請後，在下方填入金鑰。", "code": "CREDENTIALS_REQUIRED"}, 403)
        if not user_api_key.startswith("AIzaSy") or len(user_api_key) < 35:
            logger.warning(f"Invalid X-Gemini-API-Key format from IP: {ip}")
            return None, ({"error": "無效的用戶 Gemini API Key 格式", "code": "INVALID_API_KEY"}, 400)
        try:
            return genai.Client(api_key=user_api_key), None
        except Exception as e:
            logger.error(f"Failed to init Gemini client: {e}")
            return None, ({"error": "無法初始化 Gemini Client", "code": "INVALID_API_KEY"}, 400)

    elif provider == "deepseek":
        try:
            import openai
        except ImportError:
            return None, ({"error": "伺服器缺少 openai 套件，DeepSeek 不可用。", "code": "SERVER_ERROR"}, 500)

        user_api_key = headers.get("X-DeepSeek-API-Key")
        if user_api_key:
            user_api_key = user_api_key.strip()
            if not user_api_key.startswith("sk-"):
                logger.warning(f"Invalid X-DeepSeek-API-Key format from IP: {ip}")
                return None, ({"error": "無效的用戶 DeepSeek API Key 格式（必須以 sk- 開頭）", "code": "INVALID_API_KEY"}, 400)
            try:
                return openai.OpenAI(api_key=user_api_key, base_url="https://api.deepseek.com"), None
            except Exception as e:
                logger.error(f"Failed to init DeepSeek client: {e}")
                return None, ({"error": "無法初始化 DeepSeek Client", "code": "INVALID_API_KEY"}, 400)
        if not deepseek_client:
            return None, ({"error": "伺服器未設定 DeepSeek API Key。", "code": "CREDENTIALS_REQUIRED"}, 403)
        return deepseek_client, None

    elif provider == "openai_compatible":
        try:
            import openai
        except ImportError:
            return None, ({"error": "伺服器缺少 openai 套件。", "code": "SERVER_ERROR"}, 500)

        user_api_key = headers.get("X-Custom-API-Key", "").strip()
        base_url = headers.get("X-Custom-Base-URL", "").strip()
        if not user_api_key or not base_url:
            return None, ({"error": "自訂模型需要提供 API Key 與 Base URL。", "code": "CREDENTIALS_REQUIRED"}, 400)
        # SSRF guard: only allow https:// base URLs to public hosts
        try:
            parsed_base = urlparse(base_url)
        except Exception:
            return None, ({"error": "Base URL 格式無效。", "code": "VALIDATION_ERROR"}, 400)
        if parsed_base.scheme != "https":
            return None, ({"error": "Base URL 必須使用 https://。", "code": "VALIDATION_ERROR"}, 400)
        _host = (parsed_base.hostname or "").lower()
        if _host in ("localhost", "") or _host.startswith("127.") or _host.startswith("10.") \
                or _host.startswith("192.168.") or _host.startswith("169.254.") \
                or _host.startswith("172.") and 16 <= int(_host.split(".")[1]) <= 31:
            return None, ({"error": "Base URL 不可指向內部網路位址。", "code": "VALIDATION_ERROR"}, 400)
        try:
            return openai.OpenAI(api_key=user_api_key, base_url=base_url), None
        except Exception as e:
            logger.error(f"Failed to init custom OpenAI-compatible client: {e}")
            return None, ({"error": "無法初始化自訂模型 Client，請確認 API Key 與 Base URL。", "code": "INVALID_API_KEY"}, 400)

    return None, ({"error": f"不支援的 AI 模型：{provider}", "code": "VALIDATION_ERROR"}, 400)


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
    return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404

def resolve_short_url(url: str) -> str:
    """Follow redirects for Google Maps short/share URLs.

    Handles: share.google, goo.gl/maps, maps.app.goo.gl
    CID URLs (maps.google.com/?cid=) are NOT resolved here — Google requires
    JS rendering, so they fall through to Apify which handles them natively.
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname in {"share.google", "goo.gl", "maps.app.goo.gl"}:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                final_url = response.geturl()
                logger.info(f"Resolved short URL {url} → {final_url}")
                return final_url
    except Exception as e:
        logger.warning(f"Failed to resolve short URL {url}: {e}")
    return url

_ALLOWED_FETCH_HOSTS = {
    "www.google.com", "google.com", "maps.google.com", "google.com.tw",
    "www.google.com.tw", "maps.app.goo.gl", "goo.gl", "share.google",
}


def _is_allowed_url(url: str) -> bool:
    """Reject URLs that could hit internal/private hosts (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in _ALLOWED_FETCH_HOSTS
    except Exception:
        return False


def extract_place_id(url: str) -> str | None:
    # Fast path: check URL string itself for ChIJ (e.g. query_place_id=ChIJxxx, or /place/...ChIJ)
    url_match = re.search(r'(ChIJ[\w-]+)', url)
    if url_match:
        place_id = url_match.group(1)
        logger.info(f"extract_place_id found place_id '{place_id}' in URL string: {url}")
        return place_id

    # Slow path: fetch the page HTML and search for ChIJ
    # SSRF guard: only fetch from Google domains
    if not _is_allowed_url(url):
        logger.warning(f"extract_place_id rejected non-Google URL: {url}")
        return None

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
@limiter.limit("10 per minute")
def scrape():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/scrape request from IP: {ip}")
    
    data = request.get_json() or {}
    url = data.get("url")
    if not url or not isinstance(url, str):
        logger.error(f"Scrape request from {ip} failed validation: Missing or invalid field 'url'")
        return jsonify({"error": "Missing or invalid field: url (must be a non-empty string)", "code": "VALIDATION_ERROR"}), 400

    url = url.strip()
    if len(url) > 2048:
        logger.error(f"Scrape request from {ip} failed validation: URL length exceeds limit ({len(url)} > 2048)")
        return jsonify({"error": "URL length exceeds limit (max 2048 characters)", "code": "VALIDATION_ERROR"}), 400

    original_query = url
    is_url = original_query.startswith("http://") or original_query.startswith("https://")
    
    # 1. Fast path: check search_query_map first for O(1) lookup on EXACT match
    target_place_id = get_place_id_for_query(original_query)
    url_to_scrape = original_query

    # 2. If not found in mapping, try to extract or construct it
    if not target_place_id:
        if is_url:
            # First time seeing this URL. Resolve short/share links, then extract place_id
            url_to_scrape = resolve_short_url(original_query)
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
        max_reviews = min(max(int(max_reviews), 1), 500)
    except (ValueError, TypeError):
        logger.warning(f"Invalid maxReviews value received: {data.get('maxReviews')}. Defaulting to 50.")
        max_reviews = 50

    force = request.args.get("force", "false").lower() == "true"

    # Resolve Apify tokens: user-provided (for new store scraping) vs server
    # (for cheap probes and background refresh of existing cached data).
    user_apify_token = (request.headers.get("X-Apify-Token") or "").strip() or None
    server_apify_token = os.getenv("APIFY_TOKEN") or None
    apify_token = user_apify_token or server_apify_token

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
            response = {"reviews": cached, "source": "cache", "place_id": target_place_id}
            if not cached_meta:
                cached_meta = {}
            # Backfill title from original query if missing and query is a store name
            if "title" not in cached_meta and not is_url and not original_query.startswith("ChIJ"):
                cached_meta["title"] = original_query
                update_cached_metadata(target_place_id, {"title": original_query})
            response["metadata"] = cached_meta

            # Attach last_checked_at as dataAsOf for the frontend
            last_checked = get_last_checked_at(target_place_id)
            fetched = get_fetched_at(target_place_id)
            # Display the more recent of the two (or whichever exists)
            display_ts = last_checked or fetched
            if display_ts:
                response["dataAsOf"] = datetime.fromtimestamp(display_ts).strftime("%Y-%m-%d %H:%M")

            # Fire background incremental refresh if not checked in 24h
            if apify_token:
                now = time.time()
                if not last_checked or (now - last_checked) >= REFRESH_COOLDOWN_SECONDS:
                    logger.info(f"Scheduling background refresh for {target_place_id}")
                    _refresh_executor.submit(
                        _background_refresh, target_place_id, url_to_scrape, apify_token,
                    )

            return jsonify(response)

    # No token at all → can't even probe
    if not apify_token:
        logger.info(f"No cached data for {url_to_scrape}, no Apify token available — requesting credentials")
        return jsonify({
            "error": "此店家尚未收錄於資料庫，需要 Apify Token 進行即時爬取。請在下方填入您的 API 金鑰。",
            "code": "CREDENTIALS_REQUIRED",
        }), 403

    try:
        from apify_scraper import scrape_via_apify

        # If we don't have a place_id yet, do a 1-review probe just to discover
        # it. Cost: ~$0.001. If the place_id matches a pre-crawled cache entry,
        # we skip the full scrape entirely.
        if not target_place_id and not force:
            logger.info(f"No place_id found, probing Apify with 1 review for: {url_to_scrape}")
            probe_place_id, _, probe_metadata = scrape_via_apify(url_to_scrape, max_reviews=1, token=apify_token)

            # Early category gate: the 1-review probe already gives us
            # categoryName — reject non-restaurant venues before the full scrape.
            cat = (probe_metadata or {}).get("categoryName", "")
            if cat and not _is_food_category(cat):
                logger.info(f"Non-restaurant category detected via probe: '{cat}' for {url_to_scrape}")
                return jsonify({
                    "error": f"本系統僅適用於餐飲店家，偵測到此地點類別為「{cat}」，無法進行評論審計。",
                    "code": "NOT_RESTAURANT"
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

                    # Attach timestamp for frontend
                    last_checked = get_last_checked_at(probe_place_id)
                    fetched = get_fetched_at(probe_place_id)
                    display_ts = last_checked or fetched
                    if display_ts:
                        response["dataAsOf"] = datetime.fromtimestamp(display_ts).strftime("%Y-%m-%d %H:%M")

                    # Schedule background refresh if stale
                    now_ts = time.time()
                    if not last_checked or (now_ts - last_checked) >= REFRESH_COOLDOWN_SECONDS:
                        logger.info(f"Scheduling background refresh for {probe_place_id}")
                        _refresh_executor.submit(
                            _background_refresh, probe_place_id, url_to_scrape, apify_token,
                        )

                    return jsonify(response)

        # Full scrape is expensive (~$0.20-0.40 for 500 reviews). For new
        # stores (no existing cache), require the user's own Apify token.
        # Server token is reserved for cheap probes and background refresh.
        existing_cache = get_cached_reviews(target_place_id) if target_place_id else None
        if not existing_cache and not user_apify_token:
            logger.info(f"New store {url_to_scrape}, no user Apify token — requesting credentials")
            return jsonify({
                "error": "此店家尚未收錄於資料庫，需要 Apify Token 進行即時爬取。請在下方填入您的 API 金鑰。",
                "code": "CREDENTIALS_REQUIRED",
            }), 403

        scrape_token = user_apify_token or apify_token
        logger.info(f"Starting Apify scrape for URL: {url_to_scrape} (limit: {max_reviews})")
        apify_place_id, records, metadata = scrape_via_apify(url_to_scrape, max_reviews=max_reviews, token=scrape_token)

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

        # Mark this place as freshly checked + fetched
        if final_place_id:
            set_last_checked_at(final_place_id)

        logger.info(f"Apify scrape succeeded: {len(response['reviews'])} reviews in {time.time() - start_time:.2f}s.")
        if final_place_id:
            response["place_id"] = final_place_id
        if metadata:
            response["metadata"] = metadata

        # Attach timestamp for frontend
        if final_place_id:
            response["dataAsOf"] = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M")

        return jsonify(response)
    except Exception as apify_err:
        logger.warning(f"Apify scrape failed for {url_to_scrape}: {apify_err}.")

        # Map typed Apify exceptions to user-friendly error responses.
        # Internal details are logged server-side only — never sent to the client.
        from apify_scraper import ApifyTokenInvalidError, ApifyQuotaExhaustedError, ApifyRunFailedError
        if isinstance(apify_err, ApifyTokenInvalidError):
            return jsonify({"error": "Apify Token 無效或已過期，請確認後重試。", "code": "APIFY_TOKEN_INVALID"}), 401
        if isinstance(apify_err, ApifyQuotaExhaustedError):
            return jsonify({"error": "Apify 免費額度已用完，請稍後再試或更換 Token。", "code": "APIFY_QUOTA_EXHAUSTED"}), 429

        # Playwright fallback is opt-in: read at request time (not bound to a
        # module-level constant) so it can be toggled via env var / tests
        # without needing to reimport this module.
        fallback_enabled = os.getenv("ENABLE_PLAYWRIGHT_FALLBACK", "false").lower() == "true"
        if not fallback_enabled:
            logger.error(f"Playwright fallback disabled (set ENABLE_PLAYWRIGHT_FALLBACK=true to enable); returning Apify failure for {url_to_scrape}.")
            return jsonify({"error": "評論爬取失敗，請稍後再試。", "code": "SCRAPE_FAILED"}), 500

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
            pw_response = {"reviews": records, "source": "playwright_fallback"}
            if target_place_id:
                pw_response["place_id"] = target_place_id
            return jsonify(pw_response)
        except Exception as playwright_err:
            logger.error(f"Both Apify and Playwright scraping failed for {url}.")
            logger.error(f"Apify error: {apify_err}")
            logger.error(f"Playwright error: {playwright_err}")
            logger.error(traceback.format_exc())
            return jsonify({"error": "評論爬取失敗，請稍後再試。", "code": "SCRAPE_FAILED"}), 500

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
        return jsonify({"error": "Missing or invalid required field: reviews", "code": "VALIDATION_ERROR"}), 400

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
@limiter.limit("10 per minute")
def audit():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/audit request from IP: {ip}")

    data = request.get_json() or {}
    provider = data.get("provider", "gemini")
    custom_model_name = data.get("modelName")  # user-specified model for openai_compatible

    client_to_use, err_resp = _resolve_llm_client(provider, request.headers, ip)
    if err_resp:
        return jsonify(err_resp[0]), err_resp[1]

    store_name = data.get("storeName") or "待審查店家"
    place_id = data.get("placeId") or ""
    raw_reviews = data.get("reviews")
    if not raw_reviews or not isinstance(raw_reviews, list):
        logger.error(f"Audit request from {ip} failed validation: Missing or invalid required field 'reviews'")
        return jsonify({"error": "Missing or invalid required field: reviews", "code": "VALIDATION_ERROR"}), 400

    # Build per-review metadata (username, isSpikePeriod, daysElapsed for batching)
    reviews_meta = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        reviews_meta.append({
            "username": r.get("username", ""),
            "text": r.get("text", "") or "",
            "isSpikePeriod": bool(r.get("isSpikePeriod", False)),
            "daysElapsed": r.get("daysElapsed", 0),
        })

    if not reviews_meta:
        return jsonify({"results": []})

    if provider == "openai_compatible":
        model_name = custom_model_name or MODEL_NAME_OPENAI_COMPAT
    elif provider == "deepseek":
        model_name = custom_model_name or MODEL_NAME_DEEPSEEK
    else:
        model_name = MODEL_NAME_GEMINI
    prompt_version = get_prompt_version()

    # ── 1. Cache lookup ──────────────────────────────────────────
    review_ids = [f"{place_id}:{rm['username']}" for rm in reviews_meta]
    cached = get_cached_scores(review_ids, model_name, prompt_version) if place_id else {}
    cache_hits = len(cached)

    # Separate cached vs uncached reviews (preserve original indices)
    uncached_indices = [i for i, rid in enumerate(review_ids) if rid not in cached]
    uncached_reviews = [reviews_meta[i] for i in uncached_indices]

    logger.info(
        f"Auditing {len(reviews_meta)} reviews for '{store_name}': "
        f"{cache_hits} cached, {len(uncached_reviews)} to score"
    )

    # ── 2. Call LLM for uncached reviews ─────────────────────────
    llm_scores = {}  # index-in-uncached → score dict
    errors = []
    if uncached_reviews:
        batches = make_batches(uncached_reviews)
        logger.info(f"Sending {len(uncached_reviews)} reviews across {len(batches)} batch(es)...")

        flat_results = []
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_BATCHES) as executor:
            futures = {
                executor.submit(call_llm_batch, provider, client_to_use, store_name, batch, model_name=custom_model_name): (batch_idx, batch)
                for batch_idx, batch in enumerate(batches)
            }
            # Collect results, tracking which batch each came from
            batch_results = {}
            for future in as_completed(futures):
                batch_idx, batch = futures[future]
                try:
                    batch_results[batch_idx] = future.result()
                except Exception as e:
                    logger.error(f"LLM ({provider}) batch audit failed: {e}")
                    logger.error(traceback.format_exc())
                    errors.append(str(e))
                    batch_results[batch_idx] = []

            # Flatten in original batch order, remapping ids to global uncached indices
            offset = 0
            for batch_idx in range(len(batches)):
                batch_size = len(batches[batch_idx])
                for item in batch_results.get(batch_idx, []):
                    global_idx = offset + item['id']
                    llm_scores[global_idx] = item
                offset += batch_size

        # Cache newly scored reviews
        if place_id:
            to_cache = []
            for local_idx, item in llm_scores.items():
                orig_idx = uncached_indices[local_idx]
                to_cache.append({
                    "review_id": review_ids[orig_idx],
                    "I": item["incentiveIntensity"],
                    "A": item["sentimentAuthenticity"],
                    "D": item["descriptionGranularity"],
                    "reasoning": item.get("reasoning", ""),
                })
            set_cached_scores(to_cache, model_name, prompt_version)

    if errors and not llm_scores and not cached:
        return jsonify({"error": f"LLM ({provider}) 語意審計全部批次皆失敗", "code": "LLM_FAILED"}), 502

    # ── 3. Apply rules + compose results ─────────────────────────
    # Build a map from original index → scores for uncached reviews
    uncached_scores = {}
    for local_idx, item in llm_scores.items():
        orig_idx = uncached_indices[local_idx]
        uncached_scores[orig_idx] = {
            "I": item["incentiveIntensity"],
            "A": item["sentimentAuthenticity"],
            "D": item["descriptionGranularity"],
            "reasoning": item.get("reasoning", ""),
        }

    results = []
    for i, rm in enumerate(reviews_meta):
        rid = review_ids[i]
        if rid in cached:
            scores = cached[rid]
        elif i in uncached_scores:
            scores = uncached_scores[i]
        else:
            # Unscored — maintain Stage 1 ambiguous default
            results.append({
                "username": rm["username"],
                "stage2": "unscored",
            })
            continue

        result = build_stage2_result(
            username=rm["username"],
            I=scores["I"],
            A=scores["A"],
            D=scores["D"],
            reasoning=scores.get("reasoning", ""),
            is_spike=rm["isSpikePeriod"],
        )
        results.append(result)

    logger.info(
        f"Audit completed: {len(results)} reviews, {cache_hits} from cache, "
        f"{len(llm_scores)} newly scored, {len(errors)} batch failure(s), "
        f"in {time.time() - start_time:.2f}s."
    )
    response_body = {"results": results}
    if errors:
        response_body["errors"] = errors
    return jsonify(response_body)

@app.route("/api/store-summary", methods=["POST"])
def store_summary():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/store-summary request from IP: {ip}")

    data = request.get_json() or {}
    place_id = data.get("placeId")
    if not place_id or not isinstance(place_id, str) or not place_id.strip():
        return jsonify({"error": "Missing or invalid placeId", "code": "VALIDATION_ERROR"}), 400

    # Check cache first
    cached = get_cached_summary(place_id)
    if cached:
        logger.info(f"Summary cache hit for '{place_id}'")
        return jsonify(cached)

    store_name = data.get("storeName", "待審查店家")
    provider = data.get("provider", "gemini")
    custom_model_name = data.get("modelName")

    raw_reviews = data.get("reviews")
    if not raw_reviews or not isinstance(raw_reviews, list):
        return jsonify({"error": "Missing or invalid required field: reviews", "code": "VALIDATION_ERROR"}), 400

    # Filter: only real reviews with text
    valid_reviews = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        audit = r.get("audit") or {}
        if isinstance(audit, dict) and audit.get("isWashed"):
            continue
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        valid_reviews.append(r)

    # Sort by text length (descending), cap at 150
    valid_reviews.sort(key=lambda x: len(x.get("text", "")), reverse=True)
    valid_reviews = valid_reviews[:150]

    if not valid_reviews:
        result = {"warnings": [], "recommendations": []}
        return jsonify(result)

    client_to_use, err_resp = _resolve_llm_client(provider, request.headers, ip)
    if err_resp:
        return jsonify(err_resp[0]), err_resp[1]

    try:
        logger.info(f"Generating summary for '{store_name}' with {len(valid_reviews)} reviews...")
        result = call_llm_summary(provider, client_to_use, store_name, valid_reviews, model_name=custom_model_name)
        logger.info(f"Summary completed in {time.time() - start_time:.2f}s.")

        set_cached_summary(place_id, result)
        return jsonify(result)
    except Exception as e:
        logger.error(f"LLM summary ({provider}) failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "AI 總結生成失敗，請稍後再試。", "code": "LLM_FAILED"}), 502


@app.route("/api/summarize", methods=["POST"])
@limiter.limit("10 per minute")
def summarize():
    start_time = time.time()
    ip = request.remote_addr
    logger.info(f"POST /api/summarize request from IP: {ip}")

    data = request.get_json() or {}
    
    place_id = data.get("placeId")
    if not place_id or not isinstance(place_id, str) or not place_id.strip():
        return jsonify({"error": "Missing or invalid placeId", "code": "VALIDATION_ERROR"}), 400

    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Missing or invalid question", "code": "VALIDATION_ERROR"}), 400

    # Cap question length to prevent prompt injection / resource exhaustion
    if len(question) > 500:
        return jsonify({"error": "問題字數超過上限（最大 500 字）", "code": "VALIDATION_ERROR"}), 400

    raw_reviews = data.get("reviews")
    if not raw_reviews or not isinstance(raw_reviews, list):
        return jsonify({"error": "Missing or invalid required field: reviews", "code": "VALIDATION_ERROR"}), 400

    store_name = data.get("storeName", "待審查店家")
    provider = data.get("provider", "gemini")
    custom_model_name = data.get("modelName")

    # Normalize question for cache key to avoid cache misses from punctuation or spacing differences
    cache_key_question = re.sub(r'[^\w\s]', '', question).strip()

    # Semantic QA Caching (Skip LLM execution if this question was already asked for this place)
    cached_qa = get_cached_qa(place_id, cache_key_question)
    if cached_qa:
        logger.info(f"QA Cache hit for place '{place_id}', question: '{cache_key_question[:20]}...'")
        return jsonify(cached_qa)

    # Rate limiting
    if not check_and_increment_qa_limit(ip, place_id):
        return jsonify({"error": "每家店每個 IP 提問次數已達上限", "code": "RATE_LIMITED"}), 429

    # Filter real reviews (isWashed = False)
    valid_reviews = []
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        
        # Safely check if audit.isWashed is True
        audit = r.get("audit") or {}
        if isinstance(audit, dict) and audit.get("isWashed"):
            continue
            
        text = str(r.get("text") or "").strip()
        if not text:
            continue
            
        # Give an ID if not exists
        if "id" not in r:
            r["id"] = f"r{len(valid_reviews)}"
            
        valid_reviews.append(r)

    # Sort reviews by text length (descending) to prioritize the most informative ones,
    # then protect against excessive token usage by capping at 150 reviews
    valid_reviews.sort(key=lambda x: len(x.get("text", "")), reverse=True)
    valid_reviews = valid_reviews[:150]

    if not valid_reviews:
        return jsonify({
            "answer": "評論中沒有相關資訊（未找到真實有效評論）",
            "items": [],
            "sufficient": False
        })

    client_to_use, err_resp = _resolve_llm_client(provider, request.headers, ip)
    if err_resp:
        return jsonify(err_resp[0]), err_resp[1]

    # Privacy & Cost optimization: Anonymize usernames into integer indices
    # This prevents PII leakage to the LLM and saves hundreds of tokens per request
    user_map = {}
    anonymized_reviews = []
    for i, r in enumerate(valid_reviews):
        user_map[str(i)] = r.get("id") or r.get("username")
        anonymized_reviews.append({
            "id": str(i),
            "text": r.get("text", ""),
            "stars": r.get("stars", 5)
        })

    # Execute LLM QA
    try:
        logger.info(f"Summarizing for '{store_name}' with {len(valid_reviews)} anonymized reviews...")
        result = call_llm_qa(provider, client_to_use, store_name, anonymized_reviews, question, model_name=custom_model_name)
        logger.info(f"Summarize completed in {time.time() - start_time:.2f}s.")
        
        # Restore original usernames from the anonymized indices
        if result.get("items"):
            for item in result["items"]:
                mapped_id = user_map.get(str(item.get("id")))
                if mapped_id:
                    item["id"] = mapped_id
                else:
                    item["id"] = str(item.get("id"))
        
        # Save exact-match result to cache
        set_cached_qa(place_id, cache_key_question, result)
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"LLM QA ({provider}) failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "分析回答失敗，請稍後再試。", "code": "LLM_FAILED"}), 502

@app.route("/api/log-visit", methods=["POST"])
@limiter.exempt
def log_visit():
    log_visitor(request.remote_addr, "/analyzer")
    return jsonify({"ok": True})

@app.route("/api/stats", methods=["GET"])
@limiter.exempt
def stats():
    return jsonify(get_visitor_stats())

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    logger.info("Initializing Flask server configurations...")
    logger.info(f"Starting Flask server on host 0.0.0.0, port {port}...")
    app.run(host="0.0.0.0", port=port)
