from __future__ import annotations

"""
SQLite-backed cache for /api/scrape results, keyed by place_id.
Implements a dual-layer lookup: search queries / URLs map to place_id,
and place_id maps to the actual scraped reviews.
"""

import hashlib
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_rate_limit (
            session_key TEXT PRIMARY KEY,
            count INTEGER NOT NULL,
            last_reset REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_cache (
            place_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (place_id, question)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stage2_cache (
            place_id TEXT NOT NULL,
            username TEXT NOT NULL,
            review_hash TEXT NOT NULL,
            result_json TEXT NOT NULL,
            audited_at REAL NOT NULL,
            PRIMARY KEY (place_id, username)
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


def check_and_increment_qa_limit(ip: str, place_id: str, limit: int = 20, db_path: str = None) -> bool:
    """Returns True if the limit is not exceeded (and increments it), False if exceeded."""
    conn = _connect(db_path or DB_PATH)
    session_key = f"{ip}_{place_id}"
    try:
        # Prune expired rate limit records (older than 24 hours)
        conn.execute("DELETE FROM qa_rate_limit WHERE ? - last_reset >= 86400", (time.time(),))
        
        cursor = conn.execute(
            """
            INSERT INTO qa_rate_limit (session_key, count, last_reset)
            VALUES (?, 1, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                count = count + 1
            WHERE count < ?
            """,
            (session_key, time.time(), limit),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_cached_qa(place_id: str, question: str, ttl_seconds: int = CACHE_TTL_SECONDS, db_path: str = None) -> dict | None:
    """Returns the cached QA response if a fresh entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT answer_json, created_at FROM qa_cache WHERE place_id = ? AND question = ?", 
            (place_id, question)
        ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > ttl_seconds:
            return None
        return json.loads(row[0])
    finally:
        conn.close()


def set_cached_qa(place_id: str, question: str, answer_json: dict, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO qa_cache (place_id, question, answer_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(place_id, question) DO UPDATE SET
                answer_json = excluded.answer_json,
                created_at = excluded.created_at
            """,
            (place_id, question, json.dumps(answer_json, ensure_ascii=False), time.time())
        )
        conn.commit()
    finally:
        conn.close()


# ── Stage 2 (LLM) per-review cache ──────────────────────────────────────────


def _review_hash(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()[:16]


def get_cached_stage2(place_id: str, db_path: str = None) -> dict[str, dict]:
    """Returns {username: {review_hash, ...verdict fields}} for all cached Stage 2 results."""
    conn = _connect(db_path or DB_PATH)
    try:
        rows = conn.execute(
            "SELECT username, review_hash, result_json FROM stage2_cache WHERE place_id = ?",
            (place_id,)
        ).fetchall()
        result = {}
        for username, review_hash, result_json in rows:
            verdict = json.loads(result_json)
            verdict['_review_hash'] = review_hash
            result[username] = verdict
        return result
    finally:
        conn.close()


def set_cached_stage2_batch(place_id: str, results: list[dict], db_path: str = None) -> None:
    """Upsert a batch of Stage 2 verdicts. Each dict must have 'username' and 'text'."""
    conn = _connect(db_path or DB_PATH)
    try:
        now = time.time()
        for r in results:
            username = r.get('username', '')
            text = r.get('_original_text', '')
            verdict = {k: v for k, v in r.items() if k != '_original_text'}
            conn.execute(
                """
                INSERT INTO stage2_cache (place_id, username, review_hash, result_json, audited_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(place_id, username) DO UPDATE SET
                    review_hash = excluded.review_hash,
                    result_json = excluded.result_json,
                    audited_at = excluded.audited_at
                """,
                (place_id, username, _review_hash(text), json.dumps(verdict, ensure_ascii=False), now),
            )
        conn.commit()
    finally:
        conn.close()


def invalidate_stage2_cache(place_id: str, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute("DELETE FROM stage2_cache WHERE place_id = ?", (place_id,))
        conn.commit()
    finally:
        conn.close()
