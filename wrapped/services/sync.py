from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from wrapped.core.models import Scrobble
from wrapped.core.normalize import key
from wrapped.integrations.lastfm import LastfmClient

_INSERT_EVENT = """
    INSERT INTO events (
        user_id, uts, artist, artist_key, track, track_key,
        album, album_key, artist_mbid
    )
    VALUES (
        :user_id, :uts, :artist, :artist_key, :track, :track_key, 
        :album, :album_key, :artist_mbid
    )
    ON CONFLICT (
        user_id, uts, artist_key, track_key
    ) DO NOTHING
"""


@dataclass(frozen=True)
class SyncResult:
    pages: int = 0
    fetched: int = 0
    inserted: int = 0
    skipped: int = 0


def to_row(user_id: int, scrobble: Scrobble) -> dict[str, str | int | None]:
    album_key = None

    if scrobble.album is not None:
        album_key = key(scrobble.album)

    return {
        "user_id": user_id,
        "uts": scrobble.uts,
        "artist": scrobble.artist,
        "artist_key": key(scrobble.artist),
        "track": scrobble.track,
        "track_key": key(scrobble.track),
        "album": scrobble.album,
        "album_key": album_key,
        "artist_mbid": scrobble.artist_mbid,
    }


def sync_user(
    db: sqlite3.Connection,
    client: LastfmClient,
    user_id: int,
    *,
    now: int,
    max_pages: int = 1_000,
    before_commit: Callable[[SyncResult], None] | None = None,
) -> SyncResult:
    if db.in_transaction:
        raise ValueError("Sync requires a connection without an active transaction")

    user = db.execute(
        """
        SELECT lastfm_user, history_from, last_sync, paused
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    if user is None:
        raise ValueError("User not found")

    if user["paused"]:
        return SyncResult()

    if not user["lastfm_user"] or user["history_from"] is None:
        raise ValueError("User sync configuration is incomplete")

    history_from = user["history_from"]
    last_sync = user["last_sync"]

    checkpoint = history_from if last_sync is None else last_sync

    start = max(
        history_from,
        checkpoint - 12 * 3600,
    )
    end = now - 300

    if end < start or (last_sync is not None and end < last_sync):
        return SyncResult()

    fetched = client.fetch_recent(
        user["lastfm_user"],
        from_ts=start,
        to_ts=end,
        max_pages=max_pages,
    )

    rows = [
        to_row(user_id, scrobble)
        for scrobble in fetched.scrobbles
        if start <= scrobble.uts <= end
    ]

    with db:
        inserted = db.executemany(
            _INSERT_EVENT,
            rows,
        ).rowcount

        updated = db.execute(
            """
            UPDATE users
            SET last_sync = ?
            WHERE id = ?
            """,
            (end, user_id),
        )

        if updated.rowcount != 1:
            raise ValueError("User disappeared during sync")

        result = SyncResult(
            pages=fetched.pages,
            fetched=len(fetched.scrobbles),
            inserted=inserted,
            skipped=fetched.skipped,
        )

        if before_commit is not None:
            before_commit(result)

    return result
