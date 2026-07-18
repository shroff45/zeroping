# llm/cache.py
# B13.4 — LLM response cache (SQLite-backed)
# Owner: Sai
# Deps: core/config.py
#
# RULES:
#   Cache key = sha256(snapshot_hash | PROMPT_VERSION | MODEL_ID | prompt_kind)
#   If data changes     → snapshot_hash changes → cache miss → fresh generation
#   If prompt changes   → bump PROMPT_VERSION in config.py → cache miss
#   If model changes    → MODEL_ID changes → cache miss
#   Bypass: pass bypass_cache=True to skip read (Regenerate button)
#   All failures collapse to None — caller uses fallback

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from core.config import PROMPT_VERSION, MODEL_ID

CACHE_DB = Path("data/llm_cache.db")


def _get_conn() -> sqlite3.Connection:
    """
    Open (or create) the cache DB.
    Called on every operation — no persistent connection.
    SQLite handles concurrent reads safely.
    """
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            key        TEXT PRIMARY KEY,
            response   TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def cache_key(snapshot_hash: str, prompt_kind: str) -> str:
    """
    Deterministic cache key.

    snapshot_hash : 16-char hex from pipeline.run_pipeline()
    prompt_kind   : 'dashboard' | 'email_{client_name}'

    Same inputs always produce same key.
    Any input change produces a different key.
    """
    raw = f"{snapshot_hash}|{PROMPT_VERSION}|{MODEL_ID}|{prompt_kind}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get(key: str, bypass_cache: bool = False) -> str | None:
    """
    Return cached response string or None.
    Returns None if:
      - bypass_cache is True (Regenerate button path)
      - key not found
      - any DB error
    """
    if bypass_cache:
        return None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT response FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def put(key: str, response: str) -> bool:
    """
    Store response in cache.
    Returns True on success, False on any error.
    Caller does not need to handle failure — cache miss on next run
    simply regenerates.
    """
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, response) VALUES (?, ?)",
            (key, response),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def clear() -> bool:
    """
    Wipe entire cache.
    Called by Reset Demo Data button in app.py.
    Returns True on success.
    """
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM llm_cache")
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def stats() -> dict:
    """
    Return cache statistics for sidebar display.
    Never raises.
    """
    try:
        conn = _get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM llm_cache"
        ).fetchone()[0]
        conn.close()
        return {"entries": count, "db": str(CACHE_DB)}
    except Exception:
        return {"entries": 0, "db": str(CACHE_DB)}
