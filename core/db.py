# core/db.py

import sqlite3
import shutil
from pathlib import Path
from contextlib import contextmanager
import sqlalchemy as sa
from sqlalchemy.orm import Session

DB_PATH     = Path("data/ledgeai.db")
GOLDEN_PATH = Path("data/golden.db")

_engine: sa.Engine | None = None


def _apply_pragmas(conn, _):
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> sa.Engine:
    global _engine
    if _engine is None:
        _engine = sa.create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(_engine, "connect", _apply_pragmas)
    return _engine


@contextmanager
def get_session():
    with Session(get_engine()) as session:
        yield session


def reset_to_golden():
    """200ms. Works mid-demo. The entire WAL contingency in one line."""
    global _engine
    if _engine:
        _engine.dispose()
        _engine = None
    shutil.copy(GOLDEN_PATH, DB_PATH)
