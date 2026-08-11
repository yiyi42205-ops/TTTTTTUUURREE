from __future__ import annotations

"""
Primary scraping path: the Apify "compass/Google-Maps-Reviews-Scraper" actor.

server.py's /api/scrape route tries this first and falls back to the in-house
Playwright scraper (scraper.py) on any exception here — invalid token,
exhausted usage quota, run timeout, actor failure, etc. Playwright remains
untouched as the fallback path, not deleted.
"""

import os
import re
from datetime import timedelta

from apify_client import ApifyClient

from normalize import normalize_review

ACTOR_ID = "compass/Google-Maps-Reviews-Scraper"

# How long we're willing to wait for the Apify run to finish before giving up
# and letting server.py fall back to Playwright.
RUN_WAIT_SECONDS = 180

# Google Maps category keywords that indicate a food/drink establishment.
# Checked against the Apify-returned `categoryName` field (Traditional Chinese
# or English). Using substring matching so "日本料理餐廳" matches "餐廳".
FOOD_CATEGORY_KEYWORDS = [
    # Chinese
    '餐廳', '餐館', '飯店', '小吃', '麵店', '麵館', '麵食',
    '咖啡', '茶', '飲料', '飲品', '手搖',
    '火鍋', '燒烤', '燒肉', '烤肉', '鐵板燒',
    '壽司', '拉麵', '丼飯', '居酒屋', '日本料理', '韓式', '泰式', '越南',
    '甜點', '蛋糕', '麵包', '烘焙', '甜品', '冰品', '冰淇淋', '豆花',
    '便當', '自助餐', '快餐', '速食', '早餐', '早午餐', '素食',
    '酒吧', '酒館', '啤酒', '餐酒',
    '食堂', '美食', '小籠包', '水餃', '包子', '粥',
    '雞排', '滷味', '鹹酥雞', '牛肉麵', '披薩', '漢堡', '炸雞',
    # English
    'restaurant', 'cafe', 'coffee', 'bakery', 'bar', 'bistro',
    'pizza', 'burger', 'noodle', 'sushi', 'ramen',
    'fast food', 'ice cream', 'tea', 'dessert', 'grill',
    'food', 'diner', 'eatery', 'pub', 'brunch',
]

# Compiled once for performance
_FOOD_PATTERN = re.compile(
    '|'.join(re.escape(kw) for kw in FOOD_CATEGORY_KEYWORDS),
    re.IGNORECASE,
)


class NotARestaurantError(Exception):
    """Raised when the place is not a food/drink establishment."""
    pass


def _is_food_category(category_name: str) -> bool:
    """Check if a Google Maps category name indicates food/drink."""
    if not category_name:
        return False
    return bool(_FOOD_PATTERN.search(category_name))


def scrape_via_apify(url: str, max_reviews: int = 50) -> tuple[str | None, list]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("缺少 APIFY_TOKEN 環境變數，無法呼叫 Apify 爬蟲服務。")

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
        raise RuntimeError(f"Apify 執行未成功完成（狀態：{status or '無回應，可能逾時'}）。")

    dataset_id = run.default_dataset_id
    if not dataset_id:
        raise RuntimeError("Apify 執行未回傳有效的 dataset ID。")

    items = client.dataset(dataset_id).list_items().items

    place_id = None
    if items and isinstance(items[0], dict):
        place_id = items[0].get("placeId")

    # Check place category from the first item's metadata.
    # The Apify actor attaches place-level fields (title, categoryName, etc.)
    # to each review item.
    if items:
        first = items[0] if isinstance(items[0], dict) else {}
        category = first.get('categoryName') or first.get('category') or ''
        place_name = first.get('title') or first.get('name') or ''
        if category and not _is_food_category(category):
            raise NotARestaurantError(
                f'「{place_name}」的類別是「{category}」，'
                f'不是餐飲類店家。TrueRating 僅支援餐廳評論分析。'
            )

    reviews = [normalize_review(item) for item in items if isinstance(item, dict)]
    return place_id, reviews
