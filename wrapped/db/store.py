from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db
    except BaseException:
        db.close()
        raise


def initialize(db: sqlite3.Connection) -> None:
    """Install the initial schema atomically, without replacing existing data."""
    migration = (Path(__file__).parent / "migrations" / "001_initial.sql").read_text()
    try:
        db.executescript(
            "BEGIN IMMEDIATE;\n"
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);\n"
            + migration
            + "\nINSERT OR IGNORE INTO schema_version VALUES (1);\nCOMMIT;"
        )
    except BaseException:
        db.rollback()
        raise
