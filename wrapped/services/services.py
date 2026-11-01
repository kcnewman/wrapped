from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass

import requests

from wrapped.core.config import Settings
from wrapped.db.store import connect
from wrapped.integrations.lastfm import LastfmClient
from wrapped.services.alerts import TelegramAlert
from wrapped.services.jobs import _HeldLock, job
from wrapped.services.sync import SyncResult, sync_user
from wrapped.services.users import enroll_user, validate_enrollment


@dataclass(frozen=True)
class SyncJobResult:
    run_id: int
    counts: SyncResult


@dataclass
class EnrollmentJobResults:
    run_id: int
    user_id: int


def owner_alert(settings: Settings) -> TelegramAlert | None:
    if settings.telegram_token and settings.telegram_owner_chat_id:
        return TelegramAlert(settings.telegram_token, settings.telegram_owner_chat_id)

    return None


def run_sync(
    settings: Settings,
    *,
    user_id: int,
    now: int | None = None,
    held_lock: _HeldLock | None = None,
) -> SyncJobResult:
    with closing(connect(settings.database_path)) as runs_db:
        user = runs_db.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None:
            raise ValueError("User is not registered")

        with (
            job(
                "sync",
                db=runs_db,
                lock_path=settings.job_lock_path,
                user_id=user_id,
                alert=owner_alert(settings),
                held_lock=held_lock,
            ) as run,
            closing(connect(settings.database_path)) as data_db,
            requests.Session() as session,
        ):
            run_id = run.id

            if run_id is None:
                raise RuntimeError("Sync job did not produce a run ID")

            client = LastfmClient(settings.lastfm_api_key, session=session)

            def stage(result: SyncResult) -> None:
                run.pages = result.pages
                run.fetched = result.fetched
                run.inserted = result.inserted

                run.stage_success(data_db)

            try:
                result = sync_user(
                    data_db,
                    client,
                    user_id=user_id,
                    now=int(time.time()) if now is None else now,
                    before_commit=stage,
                )
            except BaseException:
                run.inserted = 0
                raise
    return SyncJobResult(run_id=run_id, counts=result)


def run_enrollment(
    settings: Settings,
    *,
    name: str,
    lastfm_user: str,
    tz: str,
    held_lock: _HeldLock | None = None,
) -> EnrollmentJobResults:
    name, lastfm_user, tz = validate_enrollment(
        name=name, lastfm_user=lastfm_user, tz=tz
    )

    with closing(connect(settings.database_path)) as runs_db:
        existing = runs_db.execute(
            """
            SELECT id
            FROM users
            WHERE lastfm_user = ? COLLATE NOCASE
            """,
            (lastfm_user,),
        ).fetchone()

        if existing is not None:
            raise ValueError("User is already registered")

        with (
            job(
                "enroll",
                db=runs_db,
                lock_path=settings.job_lock_path,
                alert=owner_alert(settings),
                held_lock=held_lock,
            ) as run,
            closing(connect(settings.database_path)) as user_db,
            requests.Session() as session,
        ):
            run_id = run.id

            if run_id is None:
                raise RuntimeError("Enrollment job did not produce a run ID")

            client = LastfmClient(settings.lastfm_api_key, session=session)

            probe_time = int(time.time())

            probe = client.fetch_recent(
                lastfm_user,
                from_ts=probe_time,
                to_ts=probe_time,
                max_pages=1,
            )

            run.pages = probe.pages

            def stage(new_user_id: int) -> None:
                previous_user_id = run.user_id
                run.user_id = new_user_id

                try:
                    run.stage_success(user_db)
                finally:
                    run.user_id = previous_user_id

            user_id = enroll_user(
                user_db, name=name, lastfm_user=lastfm_user, tz=tz, before_commit=stage
            )

            run.user_id = user_id
    return EnrollmentJobResults(run_id=run_id, user_id=user_id)
