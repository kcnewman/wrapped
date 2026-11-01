from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

LOG_FILES = {"web": "web.log", "jobs": "jobs.log"}
LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
MAX_LINES = 2_000
MAX_SCAN_BYTES = 10 * 1024 * 1024
MAX_LINE_BYTES = 128 * 1024


def _tail(path: Path, limit: int) -> Iterator[bytes]:
    """Scan backwards in blocks; don't load a whole file or an unbounded line."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            position = end
            chunks: list[bytes] = []
            newlines = 0
            while (
                position > 0 and end - position < MAX_SCAN_BYTES and newlines <= limit
            ):
                size = min(8192, position, MAX_SCAN_BYTES - (end - position))
                position -= size
                handle.seek(position)
                chunk = handle.read(size)
                chunks.append(chunk)
                newlines += chunk.count(b"\n")
            data = b"".join(reversed(chunks))
    except FileNotFoundError:
        return
    lines = data.split(b"\n")
    if position > 0:
        lines = lines[1:]  # the first line may begin outside our bounded scan
    # Only newline-terminated records are committed. Skip a partial final write.
    yield from (line for line in lines[:-1][-limit:] if len(line) <= MAX_LINE_BYTES)


def read_logs(
    log_dir: Path,
    *,
    source: str = "jobs",
    limit: int = 200,
    level: str | None = None,
    job: str | None = None,
    user: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Filter the last N physical lines, oldest first, with exact-match filters."""
    if source not in LOG_FILES:
        raise ValueError("Unknown log source")
    if not 1 <= limit <= MAX_LINES:
        raise ValueError("Invalid log limit")
    if level is not None and level not in LEVELS:
        raise ValueError("Invalid log level")
    path = log_dir / LOG_FILES[source]
    # Refuse links even though the request can never supply a path.
    if path.is_symlink():
        raise ValueError("Log files must not be symbolic links")
    records = []
    for line in _tail(path, limit):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        if not all(
            isinstance(record.get(key), str)
            for key in ("ts", "level", "logger", "event")
        ):
            continue
        if record["level"] not in LEVELS:
            continue
        if any(
            expected is not None and str(record.get(key)) != expected
            for key, expected in (
                ("level", level),
                ("job", job),
                ("user", user),
                ("run_id", run_id),
            )
        ):
            continue
        records.append(record)
    return records
