"""
SQLite-backed cache for /api/scrape results, keyed by store URL. A cache hit
within CACHE_TTL_SECONDS skips re-scraping entirely — both the Apify actor
and the Playwright fallback cost real time (and Apify usage cost), so repeat
lookups of the same store within the window are served from disk instead.
"""

import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache.db")
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scrape_cache (
            url TEXT PRIMARY KEY,
            reviews_json TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at REAL NOT NULL
        )
        """
    )
    return conn


def get_cached_reviews(url: str, db_path: str = None, ttl_seconds: int = CACHE_TTL_SECONDS):
    """Returns the cached review list if a fresh (within ttl_seconds) entry exists, else None.

    db_path defaults to the module-level DB_PATH, resolved at call time (not at
    def time) so tests can point it at a temp file via monkeypatching DB_PATH.
    """
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT reviews_json, fetched_at FROM scrape_cache WHERE url = ?", (url,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    reviews_json, fetched_at = row
    if time.time() - fetched_at > ttl_seconds:
        return None

    return json.loads(reviews_json)


def set_cached_reviews(url: str, reviews: list, source: str, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO scrape_cache (url, reviews_json, source, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                reviews_json = excluded.reviews_json,
                source = excluded.source,
                fetched_at = excluded.fetched_at
            """,
            (url, json.dumps(reviews, ensure_ascii=False), source, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
