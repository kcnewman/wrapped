from __future__ import annotations

import fcntl
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from wrapped.core.logging import log_context
from wrapped.integrations.lastfm.errors import LastfmCredentialsError

log = logging.getLogger(__name__)
Alert = Callable[[str], None]


class JobAlreadyRunning(RuntimeError):
    """Another process holds the shared writer lock; skip this invocation."""


class JobCompletionError(RuntimeError):
    """Normal completion handling failed or the outcome is uncertain."""


@dataclass
class _HeldLock:
    path: Path
    pid: int
    active: bool = True


@contextmanager
def job_lock(path: Path) -> Iterator[_HeldLock]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JobAlreadyRunning("Another job is already running") from None
        held = _HeldLock(path.resolve(), os.getpid())
        try:
            yield held
        finally:
            held.active = False
            fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass
class JobRun:
    kind: str
    user_id: int | None
    id: int | None = None
    pages: int = 0
    fetched: int = 0
    inserted: int = 0

    def counts(self) -> dict[str, int]:
        values = {
            "pages": self.pages,
            "fetched": self.fetched,
            "inserted": self.inserted,
        }
        if any(type(value) is not int or value < 0 for value in values.values()):
            raise ValueError("Run counts must be nonnegative integers")
        return values

    def stage_success(self, db: sqlite3.Connection) -> None:
        """Write success without commiting the caller's transaxtion"""
        if self.id is None:
            raise ValueError("Run has not started")

        if not db.in_transaction:
            raise ValueError("Success must be staged inside an active transaction")

        self.counts()

        _write_finish(db, self, status="success", error=None)


def notify_failure(alert: Alert | None, message: str) -> None:
    if alert is None:
        log.warning(
            "Owner alerts are not configured", extra={"event": "alert.unconfigured"}
        )
        return
    try:
        alert(message)
    except Exception as exc:  # noqa: BLE001 -- adapter failure must preserve the job error
        # An alert outage must not mask the failure that caused the alert.
        log.warning(
            "Owner alert could not be delivered",
            extra={"event": "alert.failed", "exception_type": type(exc).__name__},
        )


def _write_finish(
    db: sqlite3.Connection, run: JobRun, status: str, error: str | None
) -> None:
    cursor = db.execute(
        """
        UPDATE runs
        SET user_id = ?,
            finished_at = ?,
            pages = ?,
            fetched = ?,
            inserted = ?,
            status = ?,
            error = ?
        WHERE id = ?
        """,
        (
            run.user_id,
            int(time.time()),
            run.pages,
            run.fetched,
            run.inserted,
            status,
            error,
            run.id,
        ),
    )

    if cursor.rowcount != 1:
        raise sqlite3.DatabaseError("Run record could not be updated")


def _finish(
    db: sqlite3.Connection,
    run: JobRun,
    status: str,
    error: str | None,
) -> None:
    with db:
        _write_finish(db, run, status, error)


def _run_status(
    db: sqlite3.Connection,
    run: JobRun,
) -> str:
    row = db.execute(
        "SELECT status FROM runs WHERE id = ?",
        (run.id,),
    ).fetchone()

    if row is None:
        raise sqlite3.DatabaseError("Run record not found")

    return row[0]


@contextmanager  # pyright: ignore[reportDeprecated]
def job(
    kind: str,
    *,
    db: sqlite3.Connection,
    lock_path: Path,
    user_id: int | None = None,
    alert: Alert | None = None,
    held_lock: _HeldLock | None = None,
) -> Iterator[JobRun]:
    """Record one job independently of its application-data transaction."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind):
        raise ValueError("Invalid job kind")
    if db.in_transaction:
        raise ValueError("Run-record connection must not have an active transaction")
    if held_lock is None:
        with (
            job_lock(lock_path) as acquired,
            job(
                kind,
                db=db,
                lock_path=lock_path,
                user_id=user_id,
                alert=alert,
                held_lock=acquired,
            ) as run,
        ):
            yield run
        return
    if (
        not held_lock.active
        or held_lock.path != lock_path.resolve()
        or held_lock.pid != os.getpid()
    ):
        raise ValueError("Job lock does not belong to this process and volume")

    run = JobRun(kind, user_id)
    started = time.monotonic()
    with log_context(job=kind, run_id=None, user=user_id):
        try:
            with db:
                cursor = db.execute(
                    "INSERT INTO runs (user_id, kind, started_at, status) VALUES (?, ?, ?, 'running')",
                    (user_id, kind, int(time.time())),
                )
                run.id = cursor.lastrowid
            with log_context(run_id=run.id):
                log.info("Job started", extra={"event": "job.started"})
                yield run
                if db.in_transaction:
                    raise ValueError(
                        "Run-record connection has uncommitted application work"
                    )
                _ = run.counts()
                status = _run_status(db, run)

                if status == "running":
                    _finish(db, run, "success", None)
                elif status != "success":
                    raise sqlite3.DatabaseError("Unexpected run status")

                log.info(
                    "Job finished",
                    extra={
                        "event": "job.finished",
                        "status": "success",
                        **run.counts(),
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    },
                )
        except BaseException as exc:
            with log_context(run_id=run.id):
                commited = False

                if run.id is not None:
                    try:
                        # Roll back unfinished work on this connection before recording failure.
                        db.rollback()

                        commited = _run_status(db, run) == "success"

                        if not commited:
                            _finish(db, run, "failed", type(exc).__name__)

                    except sqlite3.Error:
                        log.critical(
                            "Job outcome could not be confirmed",
                            extra={
                                "event": "job.outcome_unknown",
                                "exception_type": type(exc).__name__,
                            },
                        )

                        notify_failure(
                            alert,
                            f"Job {kind} outcome could not be confirmed (run {run.id})",
                        )

                        raise JobCompletionError(
                            "Job outcome could not be confirmed; inspect the database"
                        ) from None

                if commited:
                    log.critical(
                        "Job commited but post-commit handling failed",
                        extra={
                            "event": "job.post_commit_failed",
                            "status": "success",
                            "exception_type": type(exc).__name__,
                        },
                    )
                    notify_failure(
                        alert,
                        f"Job {kind} commited, but post-commit handling "
                        f"failed (run {run.id}, {type(exc).__name__})",
                    )

                    raise JobCompletionError(
                        "Job data commited; post-commit handling failed."
                    ) from None

                level = (
                    logging.CRITICAL
                    if isinstance(exc, (LastfmCredentialsError, sqlite3.Error))
                    else logging.ERROR
                )

                log.log(
                    level,
                    "Job failed",
                    extra={
                        "event": "job.failed",
                        "status": "failed",
                        "exception_type": type(exc).__name__,
                    },
                )

                notify_failure(
                    alert, f"Job {kind} failed (run {run.id}, {type(exc).__name__})"
                )
            raise
