from __future__ import annotations

"""
SQLite-backed cache for /api/scrape results, keyed by place_id.
Implements a dual-layer lookup: search queries / URLs map to place_id,
and place_id maps to the actual scraped reviews.
"""

import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache.db")
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    
    # Auto-migration / flush: if the old table with 'url' as PK exists, drop it.
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(scrape_cache)")
    columns = [col[1] for col in cursor.fetchall()]
    if columns and "url" in columns:
        conn.execute("DROP TABLE scrape_cache")
        conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scrape_cache (
            place_id TEXT PRIMARY KEY,
            reviews_json TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            metadata_json TEXT
        )
        """
    )
    # Auto-migration: add metadata_json column if missing (existing DBs)
    cursor.execute("PRAGMA table_info(scrape_cache)")
    sc_columns = [col[1] for col in cursor.fetchall()]
    if "metadata_json" not in sc_columns:
        conn.execute("ALTER TABLE scrape_cache ADD COLUMN metadata_json TEXT")
        conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_query_map (
            query TEXT PRIMARY KEY,
            place_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_cache (
            place_id TEXT PRIMARY KEY,
            audit_json TEXT NOT NULL,
            audited_at REAL NOT NULL
        )
        """
    )
    return conn


def get_place_id_for_query(query: str, db_path: str = None) -> str | None:
    """Look up a normalized URL or text search in the mapping table."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT place_id FROM search_query_map WHERE query = ?", (query,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_query_place_id_mapping(query: str, place_id: str, db_path: str = None) -> None:
    """Save a mapping from a query/URL to a place_id."""
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO search_query_map (query, place_id)
            VALUES (?, ?)
            ON CONFLICT(query) DO UPDATE SET
                place_id = excluded.place_id
            """,
            (query, place_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_reviews(place_id: str, db_path: str = None, ttl_seconds: int = CACHE_TTL_SECONDS):
    """Returns the cached review list if a fresh (within ttl_seconds) entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT reviews_json, fetched_at FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    reviews_json, fetched_at = row
    if time.time() - fetched_at > ttl_seconds:
        return None

    return json.loads(reviews_json)


def get_cached_metadata(place_id: str, db_path: str = None) -> dict | None:
    """Returns the cached metadata dict (totalScore, reviewsCount) if available."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT metadata_json FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()

    if row and row[0]:
        return json.loads(row[0])
    return None


def get_cached_audit(place_id: str, db_path: str = None, ttl_seconds: int = CACHE_TTL_SECONDS):
    """Returns the cached audit result dict if a fresh entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT audit_json, audited_at FROM audit_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    audit_json, audited_at = row
    if time.time() - audited_at > ttl_seconds:
        return None

    return json.loads(audit_json)


def set_cached_audit(place_id: str, audit_result: dict, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO audit_cache (place_id, audit_json, audited_at)
            VALUES (?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                audit_json = excluded.audit_json,
                audited_at = excluded.audited_at
            """,
            (place_id, json.dumps(audit_result, ensure_ascii=False), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def invalidate_cached_audit(place_id: str, db_path: str = None) -> None:
    """Delete the audit_cache entry for a place_id so stale results aren't served."""
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute("DELETE FROM audit_cache WHERE place_id = ?", (place_id,))
        conn.commit()
    finally:
        conn.close()


def iter_all_scrape_cache(db_path: str = None):
    """Yields (place_id, reviews_list) for every entry in scrape_cache."""
    conn = _connect(db_path or DB_PATH)
    try:
        cursor = conn.execute("SELECT place_id, reviews_json FROM scrape_cache")
        for place_id, reviews_json in cursor:
            yield place_id, json.loads(reviews_json)
    finally:
        conn.close()


def get_pending_audit_entries(db_path: str = None):
    """Yields (place_id, reviews_list) for scrape_cache entries that have no audit_cache yet."""
    conn = _connect(db_path or DB_PATH)
    try:
        cursor = conn.execute(
            """
            SELECT s.place_id, s.reviews_json
            FROM scrape_cache s
            LEFT JOIN audit_cache a ON s.place_id = a.place_id
            WHERE a.place_id IS NULL
            """
        )
        for place_id, reviews_json in cursor:
            yield place_id, json.loads(reviews_json)
    finally:
        conn.close()


def set_cached_reviews(place_id: str, reviews: list, source: str, db_path: str = None, metadata: dict = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        conn.execute(
            """
            INSERT INTO scrape_cache (place_id, reviews_json, source, fetched_at, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                reviews_json = excluded.reviews_json,
                source = excluded.source,
                fetched_at = excluded.fetched_at,
                metadata_json = excluded.metadata_json
            """,
            (place_id, json.dumps(reviews, ensure_ascii=False), source, time.time(), meta_json),
        )
        # Invalidate stale audit cache when reviews are refreshed
        conn.execute("DELETE FROM audit_cache WHERE place_id = ?", (place_id,))
        conn.commit()
    finally:
        conn.close()
