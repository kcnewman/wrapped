from __future__ import annotations


class LastfmError(Exception):
    def __init__(
        self, message: str, *, status: int | None = None, code: int | None = None
    ) -> None:
        details = ", ".join(
            f"{name}={value}"
            for name, value in (("status", status), ("code", code))
            if value is not None
        )
        super().__init__(f"{message} ({details})" if details else message)
        self.status = status
        self.code = code


class LastfmTransientError(LastfmError):
    """Network trouble, rate limiting, a temporary outage or a garbled reply."""


class LastfmPermanentError(LastfmError):
    """The request itself is the problem; retrying it unchanged will not help."""


class LastfmBadRequest(LastfmPermanentError):
    """A parameter was rejected. This is a bug in our code."""


class LastfmCredentialsError(LastfmPermanentError):
    """The API key was rejected or suspended. Alert the owner."""


class LastfmUserNotFound(LastfmPermanentError):
    """The username does not exist (or is no longer visible)."""


class LastfmProtocolError(LastfmPermanentError):
    """Last.fm answered, but not in the shape we expect: the API may have changed."""


class LastfmPageLimitError(LastfmPermanentError):
    """The requested window needs more pages than we allow in one run."""
