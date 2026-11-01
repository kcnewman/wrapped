from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from contextlib import closing

from wrapped.core.config import load_settings
from wrapped.core.logging import configure_logging
from wrapped.db.store import connect, initialize
from wrapped.integrations.lastfm import LastfmError
from wrapped.services.jobs import (
    JobAlreadyRunning,
    JobCompletionError,
    job,
    job_lock,
    notify_failure,
)
from wrapped.services.logview import LEVELS, read_logs
from wrapped.services.services import owner_alert, run_enrollment, run_sync

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wrapped operational tools")
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser(
        "check", help="Initialize/check SQLite and record a check job"
    )

    sync = commands.add_parser(
        "sync",
        help="Sync a registered user",
    )
    _ = sync.add_argument("--user", required=True, help="Last.fm username")

    user = commands.add_parser(
        "user",
        help="Manage registered users",
    )

    user_commands = user.add_subparsers(
        dest="user_command",
        required=True,
    )

    add_user = user_commands.add_parser(
        "add",
        help="Register a user",
    )

    logs = commands.add_parser("logs", help="Read a filtered application log tail")

    _ = add_user.add_argument("--user", required=True)
    _ = add_user.add_argument("--name", required=True)
    _ = add_user.add_argument("--tz", required=True)

    _ = logs.add_argument("--source", choices=("web", "jobs"), default="jobs")
    _ = logs.add_argument("--limit", type=int, default=200)
    _ = logs.add_argument("--level", choices=sorted(LEVELS))
    _ = logs.add_argument("--job")
    _ = logs.add_argument("--user")
    _ = logs.add_argument("--run-id")
    args = parser.parse_args(argv)
    settings = load_settings()

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
            parser.error("Invalid log filter or source")
        except OSError:
            parser.exit(
                status=1,
                message="Log source unavailable. \n",
            )

        for record in records:
            print(json.dumps(record, ensure_ascii=True))

        return 0

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

                if args.command == "user":
                    try:
                        with closing(db):
                            enrollment = run_enrollment(
                                settings,
                                name=args.name,
                                lastfm_user=args.user,
                                tz=args.tz,
                                held_lock=held_lock,
                            )

                        print(
                            f"Registered user {enrollment.user_id} "
                            f"(run {enrollment.run_id}). "
                            "Collection starts from enrollment"
                        )
                        return 0

                    except JobCompletionError as exc:
                        print(str(exc))
                        return 1
                    except ValueError as exc:
                        print(str(exc))
                        return 2

                    except (LastfmError, sqlite3.Error, OSError):
                        print("Enrollment failed. Inspect jobs.log for details.")
                        return 1

                if args.command == "sync":
                    try:
                        with closing(db):
                            user = db.execute(
                                """
                                SELECT id, paused
                                FROM users
                                WHERE lastfm_user = ? COLLATE NOCASE
                                """,
                                (args.user.strip(),),
                            ).fetchone()

                            if user is None:
                                print("User is not registered.")
                                return 2

                            if user["paused"]:
                                print("User is paused; sync skipped.")
                                return 0

                            synced = run_sync(
                                settings,
                                user_id=user["id"],
                                held_lock=held_lock,
                            )
                        result = synced.counts

                        print(
                            f"Run {synced.run_id}: "
                            f"pages={result.pages}, "
                            f"fetched={result.fetched}, "
                            f"inserted={result.inserted}, "
                            f"skipped={result.skipped}"
                        )

                    except JobCompletionError as exc:
                        print(str(exc))
                        return 1

                    except (LastfmError, sqlite3.Error, ValueError, OSError):
                        print("Sync failed. Inspect jobs.log for details.")
                        return 1

                    return 0

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
                except JobCompletionError as exc:
                    print(str(exc))
                    return 1

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
