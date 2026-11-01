from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS = (
    "001_initial.sql",
    "002_users_lastfm_nocase.sql",
)


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


def _execute_migration(db: sqlite3.Connection, sql: str) -> None:
    start = 0

    for index, char in enumerate(sql):
        if char != ";":
            continue

        statement = sql[start : index + 1]

        if sqlite3.complete_statement(statement):
            _ = db.execute(statement)
            start = index + 1

    remainder = sql[start:].strip()

    if remainder:
        _ = db.execute(remainder)


def initialize(db: sqlite3.Connection) -> None:
    """Apply migrations in one transaction"""
    if db.in_transaction:
        raise ValueError("Migration require a connection without an active transaction")

    migration_dir = Path(__file__).parent / "migrations"

    with db:
        _ = db.execute("BEGIN IMMEDIATE")
        _ = db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        applied = {row[0] for row in db.execute("SELECT version FROM schema_version")}
        supported = set(range(1, len(_MIGRATIONS) + 1))

        if not applied <= supported:
            raise sqlite3.DatabaseError(
                "Database contains an unsupported migration version"
            )

        if applied != set(range(1, len(applied) + 1)):
            raise sqlite3.DatabaseError("Database migration history contains a gap")

        for version, filename in enumerate(_MIGRATIONS, start=1):
            if version in applied:
                continue

            sql = (migration_dir / filename).read_text(encoding="utf-8")

            _execute_migration(db, sql)
            _ = db.execute(
                """
                INSERT INTO schema_version (version)
                VALUES (?)
                """,
                (version,),
            )
