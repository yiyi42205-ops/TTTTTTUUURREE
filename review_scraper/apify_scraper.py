from __future__ import annotations

"""
Primary scraping path: the Apify "compass/Google-Maps-Reviews-Scraper" actor.

server.py's /api/scrape route tries this first and falls back to the in-house
Playwright scraper (scraper.py) on any exception here — invalid token,
exhausted usage quota, run timeout, actor failure, etc. Playwright remains
untouched as the fallback path, not deleted.
"""

import os
from datetime import timedelta

from apify_client import ApifyClient

from normalize import normalize_review

ACTOR_ID = "compass/Google-Maps-Reviews-Scraper"

# How long we're willing to wait for the Apify run to finish before giving up
# and letting server.py fall back to Playwright.
RUN_WAIT_SECONDS = 180


class ApifyTokenInvalidError(RuntimeError):
    """Raised when the Apify token is missing or rejected by the API."""

class ApifyQuotaExhaustedError(RuntimeError):
    """Raised when the Apify free-tier quota is exhausted."""

class ApifyRunFailedError(RuntimeError):
    """Raised when the Apify actor run fails or times out."""


def scrape_via_apify(url: str, max_reviews: int = 50, token: str | None = None) -> tuple[str | None, list, dict]:
    token = token or os.getenv("APIFY_TOKEN")
    if not token:
        raise ApifyTokenInvalidError("缺少 APIFY_TOKEN，無法呼叫 Apify 爬蟲服務。")

    client = ApifyClient(token)

    run_input = {
        "startUrls": [{"url": url}],
        "maxReviews": max_reviews,
        "reviewsSort": "newest",
        "language": "zh-TW",
    }

    run = client.actor(ACTOR_ID).call(
        run_input=run_input,
        wait_duration=timedelta(seconds=RUN_WAIT_SECONDS),
    )

    # run is an apify_client Run object (a Pydantic model with attribute access:
    # run.status, run.default_dataset_id) — NOT a dict. Using run.get(...) here
    # raises AttributeError even when the Apify run itself succeeded.
    status = run.status if run else None
    if status != "SUCCEEDED":
        raise ApifyRunFailedError(f"Apify 執行未成功完成（狀態：{status or '無回應，可能逾時'}）。")

    dataset_id = run.default_dataset_id
    if not dataset_id:
        raise ApifyRunFailedError("Apify 執行未回傳有效的 dataset ID。")

    items = client.dataset(dataset_id).list_items().items
    
    place_id = None
    metadata = {}
    if items and isinstance(items[0], dict):
        first = items[0]
        place_id = first.get("placeId")
        if first.get("totalScore") is not None:
            metadata["totalScore"] = first["totalScore"]
        if first.get("reviewsCount") is not None:
            metadata["reviewsCount"] = first["reviewsCount"]
        if first.get("categoryName") is not None:
            metadata["categoryName"] = first["categoryName"]
        if first.get("title") is not None:
            metadata["title"] = first["title"]

    reviews = [normalize_review(item) for item in items if isinstance(item, dict)]
    return place_id, reviews, metadata
