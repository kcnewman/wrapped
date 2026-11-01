from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_enrollment(
    *, name: str, lastfm_user: str, tz: str
) -> tuple[str, str, str]:
    name = name.strip()
    lastfm_user = lastfm_user.strip()
    tz = tz.strip()

    if not name:
        raise ValueError("Name must not be blank")

    if not lastfm_user:
        raise ValueError("Last.fm username must not be blank")

    if not tz:
        raise ValueError("Timezone must not be blank")

    try:
        _ = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown or unsupported timezone") from None

    return name, lastfm_user, tz


def enroll_user(
    db: sqlite3.Connection,
    *,
    name: str,
    lastfm_user: str,
    tz: str,
    before_commit: Callable[[int], None] | None = None,
) -> int:
    if db.in_transaction:
        raise ValueError(
            "Enrollement requires a connection without an active transaction"
        )

    name, lastfm_user, tz = validate_enrollment(
        name=name,
        lastfm_user=lastfm_user,
        tz=tz,
    )

    history_from = int(time.time())

    with db:
        cursor = db.execute(
            """
            INSERT INTO users (
                name, lastfm_user, tz, history_from
            )
            VALUES (?,?,?,?)
            ON CONFLICT (lastfm_user COLLATE NOCASE) DO NOTHING
            """,
            (name, lastfm_user, tz, history_from),
        )

        if cursor.rowcount == 0:
            raise ValueError("User is already registered")

        user_id = cursor.lastrowid

        if user_id is None:
            raise RuntimeError("Enrollment did not produce a user ID")

        if before_commit is not None:
            before_commit(user_id)

    return user_id
