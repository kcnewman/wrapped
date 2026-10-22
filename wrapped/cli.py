from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from contextlib import closing

from wrapped.core.config import Settings, load_settings
from wrapped.core.logging import configure_logging
from wrapped.db.store import connect, initialize
from wrapped.services.alerts import TelegramAlert
from wrapped.services.jobs import JobAlreadyRunning, job, job_lock, notify_failure
from wrapped.services.logview import LEVELS, read_logs

log = logging.getLogger(__name__)


def owner_alert(settings: Settings) -> TelegramAlert | None:
    if settings.telegram_token and settings.telegram_owner_chat_id:
        return TelegramAlert(settings.telegram_token, settings.telegram_owner_chat_id)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wrapped operational tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Initialize/check SQLite and record a check job")
    logs = commands.add_parser("logs", help="Read a filtered application log tail")
    logs.add_argument("--source", choices=("web", "jobs"), default="jobs")
    logs.add_argument("--limit", type=int, default=200)
    logs.add_argument("--level", choices=sorted(LEVELS))
    logs.add_argument("--job")
    logs.add_argument("--user")
    logs.add_argument("--run-id")
    args = parser.parse_args(argv)
    settings = load_settings()
    alert = owner_alert(settings)
    try:
        with job_lock(settings.job_lock_path) as held_lock:
            handler = configure_logging(
                "jobs",
                log_dir=settings.log_dir,
                secrets=settings.redactions,
                level=settings.log_level,
            )
            try:
                if args.command == "logs":
                    try:
                        records = read_logs(
                            settings.log_dir,
                            source=args.source,
                            limit=args.limit,
                            level=args.level,
                            job=args.job,
                            user=args.user,
                            run_id=args.run_id,
                        )
                    except ValueError:
                        parser.error("Invalid log filter")
                    for record in records:
                        print(json.dumps(record, ensure_ascii=True))
                    return 0
                db = None
                try:
                    db = connect(settings.database_path)
                    initialize(db)
                except (sqlite3.Error, OSError) as exc:
                    if db is not None:
                        db.close()
                    log.critical(
                        "Database startup failed",
                        extra={
                            "event": "database.unavailable",
                            "exception_type": type(exc).__name__,
                        },
                    )
                    notify_failure(alert, "Wrapped database startup failed")
                    return 1
                try:
                    with (
                        closing(db),
                        job(
                            "check",
                            db=db,
                            lock_path=settings.job_lock_path,
                            alert=alert,
                            held_lock=held_lock,
                        ),
                    ):
                        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise sqlite3.DatabaseError("Database check failed")
                except sqlite3.Error:
                    return 1  # The runner already recorded and alerted the failure.
                return 0
            finally:
                logging.getLogger().removeHandler(handler)
                handler.close()
    except JobAlreadyRunning:
        print("Another job is already running; skipped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
