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

DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache.db")
# No TTL — cache entries are permanent until overwritten by a fresh scrape.


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # WAL mode: allows concurrent reads while writing, critical for gevent workers
    conn.execute("PRAGMA journal_mode=WAL")

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
    if "last_checked_at" not in sc_columns:
        conn.execute("ALTER TABLE scrape_cache ADD COLUMN last_checked_at REAL")
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
        CREATE TABLE IF NOT EXISTS summary_cache (
            place_id TEXT PRIMARY KEY,
            summary_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visitor_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            path TEXT NOT NULL,
            visited_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stage2_scores (
            review_id TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            I INTEGER NOT NULL,
            A INTEGER NOT NULL,
            D INTEGER NOT NULL,
            reasoning TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (review_id, model, prompt_version)
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


def get_cached_reviews(place_id: str, db_path: str = None):
    """Returns the cached review list if an entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT reviews_json FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return json.loads(row[0])



def get_last_checked_at(place_id: str, db_path: str = None) -> float | None:
    """Returns the last_checked_at timestamp (UNIX) for a place_id, or None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT last_checked_at FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def set_last_checked_at(place_id: str, db_path: str = None) -> None:
    """Update last_checked_at to now for an existing scrape_cache entry."""
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            "UPDATE scrape_cache SET last_checked_at = ? WHERE place_id = ?",
            (time.time(), place_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_fetched_at(place_id: str, db_path: str = None) -> float | None:
    """Returns the fetched_at timestamp (UNIX) for a place_id, or None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT fetched_at FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


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


def update_cached_metadata(place_id: str, updates: dict, db_path: str = None) -> None:
    """Merge updates into the existing metadata_json for a place_id."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT metadata_json FROM scrape_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
        if row and row[0]:
            meta = json.loads(row[0])
        else:
            meta = {}
        meta.update(updates)
        conn.execute(
            "UPDATE scrape_cache SET metadata_json = ? WHERE place_id = ?",
            (json.dumps(meta, ensure_ascii=False), place_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_audit(place_id: str, db_path: str = None):
    """Returns the cached audit result dict if an entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT audit_json FROM audit_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return json.loads(row[0])


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
                metadata_json = COALESCE(excluded.metadata_json, scrape_cache.metadata_json)
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


def get_cached_qa(place_id: str, question: str, db_path: str = None) -> dict | None:
    """Returns the cached QA response if an entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT answer_json FROM qa_cache WHERE place_id = ? AND question = ?",
            (place_id, question)
        ).fetchone()
        if not row:
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


# ── Store summary cache ────────────────────────────────────────

def get_cached_summary(place_id: str, db_path: str = None) -> dict | None:
    """Returns the cached store summary dict if an entry exists, else None."""
    conn = _connect(db_path or DB_PATH)
    try:
        row = conn.execute(
            "SELECT summary_json FROM summary_cache WHERE place_id = ?", (place_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return json.loads(row[0])


def set_cached_summary(place_id: str, summary: dict, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO summary_cache (place_id, summary_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                summary_json = excluded.summary_json,
                created_at = excluded.created_at
            """,
            (place_id, json.dumps(summary, ensure_ascii=False), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


# ── Visitor counter ────────────────────────────────────────────

def log_visitor(ip: str, path: str, db_path: str = None) -> None:
    conn = _connect(db_path or DB_PATH)
    try:
        conn.execute(
            "INSERT INTO visitor_log (ip, path, visited_at) VALUES (?, ?, ?)",
            (ip, path, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_visitor_stats(db_path: str = None) -> dict:
    conn = _connect(db_path or DB_PATH)
    try:
        now = time.time()
        day_ago = now - 86400
        week_ago = now - 604800

        total = conn.execute("SELECT COUNT(*) FROM visitor_log").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM visitor_log WHERE visited_at >= ?", (day_ago,)
        ).fetchone()[0]
        week = conn.execute(
            "SELECT COUNT(*) FROM visitor_log WHERE visited_at >= ?", (week_ago,)
        ).fetchone()[0]

        return {"total": total, "today": today, "week": week}
    finally:
        conn.close()


# ── Stage 2 score cache ─────────────────────────────────────────

def get_cached_scores(review_ids: list, model: str, prompt_version: str,
                      db_path: str = None) -> dict:
    """Return {review_id: {I, A, D, reasoning}} for any cached scores."""
    if not review_ids:
        return {}
    conn = _connect(db_path or DB_PATH)
    try:
        placeholders = ",".join("?" for _ in review_ids)
        rows = conn.execute(
            f"""
            SELECT review_id, I, A, D, reasoning
            FROM stage2_scores
            WHERE review_id IN ({placeholders})
              AND model = ? AND prompt_version = ?
            """,
            [*review_ids, model, prompt_version],
        ).fetchall()
        return {
            row[0]: {"I": row[1], "A": row[2], "D": row[3], "reasoning": row[4]}
            for row in rows
        }
    finally:
        conn.close()


def set_cached_scores(scores: list, model: str, prompt_version: str,
                      db_path: str = None) -> None:
    """Bulk-insert score rows. Each item: {review_id, I, A, D, reasoning}."""
    if not scores:
        return
    conn = _connect(db_path or DB_PATH)
    try:
        now = time.time()
        conn.executemany(
            """
            INSERT INTO stage2_scores (review_id, model, prompt_version, I, A, D, reasoning, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id, model, prompt_version) DO UPDATE SET
                I = excluded.I,
                A = excluded.A,
                D = excluded.D,
                reasoning = excluded.reasoning,
                created_at = excluded.created_at
            """,
            [
                (s["review_id"], model, prompt_version,
                 s["I"], s["A"], s["D"], s["reasoning"], now)
                for s in scores
            ],
        )
        conn.commit()
    finally:
        conn.close()
