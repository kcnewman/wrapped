from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_context: ContextVar[dict[str, str | int | None] | None] = ContextVar(
    "log_context", default=None
)
_EVENT = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")
_FIELDS = (
    "page",
    "pages",
    "fetched",
    "inserted",
    "skipped",
    "where",
    "attempt",
    "max_attempts",
    "exception_type",
    "status",
    "duration_ms",
)


@contextmanager
def log_context(**values: str | int | None) -> Iterator[None]:
    unknown = values.keys() - {"job", "run_id", "user"}
    if unknown:
        raise ValueError("Unknown logging context field")
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _context.get() or {}
        for key in ("job", "run_id", "user"):
            setattr(record, key, context.get(key))
        return True


class RedactionFilter(logging.Filter):
    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def redact(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            # Do not leave the formatter's cached exception text unredacted.
            record.exc_text = self.redact(
                logging.Formatter().formatException(record.exc_info)
            )
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: RedactionFilter | None = None) -> None:
        super().__init__()
        self.redactor = redactor or RedactionFilter()

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", "application.message")
        if not isinstance(event, str) or not _EVENT.fullmatch(event):
            event = "application.message"
        data: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
            "job": getattr(record, "job", None),
            "run_id": getattr(record, "run_id", None),
            "user": getattr(record, "user", None),
            "message": record.getMessage(),
        }
        for name in _FIELDS:
            value = getattr(record, name, None)
            if isinstance(value, (str, int, float, bool)):
                data[name] = value
        if record.exc_info or record.exc_text:
            data["exception"] = record.exc_text or self.formatException(record.exc_info)  # type: ignore[arg-type]
        if record.stack_info:
            data["stack"] = record.stack_info
        return json.dumps(
            {
                k: self.redactor.redact(v) if isinstance(v, str) else v
                for k, v in data.items()
            },
            ensure_ascii=True,
            allow_nan=False,
        )


def configure_logging(
    kind: str,
    *,
    log_dir: Path,
    secrets: Sequence[str] = (),
    level: str = "INFO",
) -> RotatingFileHandler:

    if kind not in {"web", "jobs"}:
        raise ValueError("Logging kind must be web or jobs")
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid log level")
    log_dir.mkdir(parents=True, exist_ok=True)
    redactor = RedactionFilter(secrets)
    handler = RotatingFileHandler(
        log_dir / f"{kind}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.addFilter(ContextFilter())
    handler.addFilter(redactor)
    handler.setFormatter(JsonFormatter(redactor))
    root = logging.getLogger()
    for previous in root.handlers[:]:
        root.removeHandler(previous)
        previous.close()
    root.setLevel(level)
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for previous in logger.handlers[:]:
            logger.removeHandler(previous)
            previous.close()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpcore", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return handler
