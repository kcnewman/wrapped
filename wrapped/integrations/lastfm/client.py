from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from wrapped.core.models import Scrobble
from wrapped.core.retry import retry_call
from wrapped.integrations.lastfm.errors import (
    LastfmBadRequest,
    LastfmCredentialsError,
    LastfmError,
    LastfmPageLimitError,
    LastfmPermanentError,
    LastfmProtocolError,
    LastfmTransientError,
    LastfmUserNotFound,
)
from wrapped.integrations.lastfm.schema import parse_page

_URL = "https://ws.audioscrobbler.com/2.0/"
_TIMEOUT = (3.05, 15.0)  # (connect, read) seconds
_USER_AGENT = "wrapped/0.1"
MAX_PAGE_SIZE = 200  # API allows 1000

_CREDENTIAL_CODES = frozenset({4, 9, 10, 26})
_TRANSIENT_CODES = frozenset({8, 11, 16, 29})
_BAD_REQUEST_CODES = frozenset({2, 3, 5, 6, 7, 13})

_TRANSPORT_ERRORS = (
    requests.Timeout,
    requests.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


def classify(status: int, code: int | None) -> LastfmError | None:
    """Returns None for success, otherwise the exception to raise."""
    if status == 404 and code == 6:
        return LastfmUserNotFound("Last.fm user not found", status=status, code=code)
    if code in _CREDENTIAL_CODES:
        return LastfmCredentialsError(
            "Last.fm credentials rejected", status=status, code=code
        )
    if status == 429 or 500 <= status <= 599 or code in _TRANSIENT_CODES:
        return LastfmTransientError(
            "Last.fm temporarily unavailable", status=status, code=code
        )
    if status == 400 or code in _BAD_REQUEST_CODES:
        return LastfmBadRequest(
            "Last.fm rejected the request", status=status, code=code
        )
    if code is not None:
        return LastfmPermanentError(
            "Last.fm returned an unrecognised error", status=status, code=code
        )
    if status != 200:
        return LastfmPermanentError(
            "Unexpected HTTP status from Last.fm", status=status
        )
    return None


def _read_json(response: requests.Response) -> object:
    """The parsed body, or None when the body is not JSON."""
    try:
        return response.json()
    except ValueError:
        return None


def _error_code(body: object) -> int | None:
    if isinstance(body, dict):
        code = body.get("error")
        if isinstance(code, int):
            return code
    return None


@dataclass(frozen=True, slots=True)
class RecentFetch:
    scrobbles: list[Scrobble]  # newest first
    pages: int
    skipped: int


class LastfmClient:
    """Synchronous Last.fm client."""

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._api_key = api_key.strip()
        self._session = session if session is not None else requests.Session()
        self._max_attempts = max_attempts
        self._sleep = sleep

    def _send_once(self, params: dict[str, str | int]) -> dict[str, Any]:
        """One HTTP request. Returns the JSON object or raises a Lastfm error."""
        try:
            response = self._session.get(
                _URL,
                params={
                    **params,
                    "method": "user.getRecentTracks",
                    "api_key": self._api_key,
                    "format": "json",
                },
                headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            )
        except _TRANSPORT_ERRORS:
            raise LastfmTransientError("Last.fm transport failed") from None
        except requests.RequestException:
            raise LastfmPermanentError("Last.fm request could not be sent") from None

        try:
            body = _read_json(response)
            error = classify(response.status_code, _error_code(body))
            if error is not None:
                raise error
            if body is None:
                raise LastfmTransientError(
                    "Last.fm returned non-JSON data", status=response.status_code
                )
            if not isinstance(body, dict):
                raise LastfmProtocolError(
                    "Expected a JSON object", status=response.status_code
                )
            return body
        finally:
            response.close()

    def _get(self, params: dict[str, str | int]) -> dict[str, Any]:
        """`_send_once`, retried only when the failure is transient."""
        return retry_call(
            lambda: self._send_once(params),
            retry_on=LastfmTransientError,
            max_attempts=self._max_attempts,
            sleep=self._sleep,
        )

    def fetch_recent(
        self,
        username: str,
        *,
        from_ts: int,
        to_ts: int,
        page_size: int = MAX_PAGE_SIZE,
        max_pages: int = 1_000,
    ) -> RecentFetch:
        """Fetch every completed scrobble in [from_ts, to_ts], newest first."""
        username = username.strip()
        if not username:
            raise ValueError("username must not be blank")
        if from_ts < 0 or to_ts < 0:
            raise ValueError("timestamps must not be negative")
        if from_ts > to_ts:
            # The API silently accepts this and returns "no scrobbles", which would
            # make a swapped argument look like a quiet listener.
            raise ValueError("from_ts must not be after to_ts")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        scrobbles: list[Scrobble] = []
        skipped = 0
        page = 1
        while True:
            payload = self._get(
                {
                    "user": username,
                    "from": from_ts,
                    "to": to_ts,
                    "limit": page_size,
                    "page": page,
                }
            )
            parsed = parse_page(payload, username, page)
            if parsed.total_pages > max_pages:
                raise LastfmPageLimitError(
                    "Window needs more pages than max_pages allows"
                )
            scrobbles.extend(parsed.scrobbles)
            skipped += parsed.skipped
            if page >= parsed.total_pages:
                return RecentFetch(scrobbles, pages=page, skipped=skipped)
            page += 1
