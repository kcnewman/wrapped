from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from wrapped.core.models import Scrobble
from wrapped.integrations.lastfm.errors import LastfmProtocolError

log = logging.getLogger(__name__)


def _blank_to_none(value: object) -> object:
    """Last.fm writes "" for 'unknown'; we write None."""
    if isinstance(value, str):
        return value.strip() or None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class _Artist(_Model):
    name: str = Field(alias="#text", min_length=1)
    mbid: OptionalText = None


class _Album(_Model):
    name: OptionalText = Field(default=None, alias="#text")


class _Date(_Model):
    uts: int = Field(ge=0)


class _Track(_Model):
    name: str = Field(min_length=1)
    artist: _Artist
    date: _Date
    album: _Album = Field(default_factory=_Album)
    mbid: OptionalText = None


class _PageMeta(_Model):
    page: int = Field(ge=1)
    total_pages: int = Field(alias="totalPages", ge=0)


def _is_now_playing(row: object) -> bool:
    return (
        isinstance(row, dict)
        and isinstance(row.get("@attr"), dict)
        and row["@attr"].get("nowplaying") == "true"
    )


class _RecentTracks(_Model):
    meta: _PageMeta = Field(alias="@attr")
    rows: list[dict[str, Any]] = Field(default_factory=list, alias="track")

    @field_validator("rows", mode="before")
    @classmethod
    def normalize_rows(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return value  # let normal validation reject it
        return [row for row in value if not _is_now_playing(row)]


class _RecentResponse(_Model):
    recenttracks: _RecentTracks


@dataclass(frozen=True, slots=True)
class ParsedPage:
    scrobbles: list[Scrobble]
    total_pages: int
    skipped: int  # rows we could not read; the caller should record this


def _where(exc: ValidationError) -> str:
    first = exc.errors(include_input=False, include_url=False)[0]
    path = ".".join(str(part) for part in first["loc"]) or "<root>"
    return f"{path} ({first['type']})"


def parse_page(payload: Any, username: str, page: int) -> ParsedPage:
    """Turn one `user.getRecentTracks` response into Scrobbles.
    A wrong *row* is skipped and counted, so one odd scrobble cannot block a user forever.
    """
    try:
        recent = _RecentResponse.model_validate(payload).recenttracks
    except ValidationError as exc:
        raise LastfmProtocolError(f"Malformed Last.fm page at {_where(exc)}") from None

    if recent.meta.page != page:
        raise LastfmProtocolError("Last.fm returned a different page than requested")
    if recent.meta.total_pages == 0 and recent.rows:
        raise LastfmProtocolError("Last.fm returned scrobbles for zero pages")

    scrobbles: list[Scrobble] = []
    skipped = 0
    first_where = None
    for row in recent.rows:
        try:
            track = _Track.model_validate(row)
            scrobbles.append(
                Scrobble(
                    username=username,
                    uts=track.date.uts,
                    artist=track.artist.name,
                    track=track.name,
                    album=track.album.name,
                    artist_mbid=track.artist.mbid,
                    track_mbid=track.mbid,
                )
            )
        except ValidationError as exc:
            skipped += 1
            if first_where is None:
                first_where = _where(exc)

    if skipped:
        log.warning(
            "Skipped malformed scrobbles",
            extra={
                "event": "scrobble.skipped",
                "page": page,
                "skipped": skipped,
                "where": first_where,
            },
        )

    return ParsedPage(scrobbles, recent.meta.total_pages, skipped)
