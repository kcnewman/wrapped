import asyncio
import json
import logging

import pytest

from wrapped.core.logging import configure_logging, log_context
from wrapped.core.retry import retry_call
from wrapped.integrations.lastfm.schema import parse_page

log = logging.getLogger(__name__)


def records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_context_is_nested_and_isolated_between_async_tasks(json_logs):
    async def worker(name):
        with log_context(job=name, run_id=name, user=42):
            await asyncio.sleep(0)
            log.info("Worker", extra={"event": "worker.started"})
            with log_context(user=43):
                log.info("Nested", extra={"event": "worker.nested"})
            log.info("Restored", extra={"event": "worker.restored"})

    async def run():
        await asyncio.gather(worker("sync"), worker("report"))

    asyncio.run(run())
    log.info("Outside", extra={"event": "worker.outside"})
    entries = records(json_logs)
    assert all(row["run_id"] == row["job"] for row in entries[:-1])
    assert [row["user"] for row in entries[:-1]] == [42, 43, 42, 42, 43, 42]
    assert entries[-1]["job"] is None
    assert entries[-1]["run_id"] is None
    assert entries[-1]["user"] is None


def test_json_lines_escape_newlines_and_redact_messages_exceptions_and_fields(
    json_logs,
):
    with log_context(job="sync", run_id=7, user=42):
        try:
            raise RuntimeError("test-api-secret\nsecond exception line")
        except RuntimeError:
            log.exception(
                "Failure %s\nforged line",
                "test-api-secret",
                extra={
                    "event": "test.failed",
                    "where": "test-api-secret",
                    "artist": "never serialized",
                },
            )
    lines = json_logs.getvalue().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert "test-api-secret" not in lines[0]
    assert "[REDACTED]" in row["message"]
    assert "RuntimeError: [REDACTED]\nsecond exception line" in row["exception"]
    assert row["where"] == "[REDACTED]"
    assert "artist" not in row
    assert row["ts"].endswith("Z")
    assert row["event"] == "test.failed"


def test_configuration_rotates_and_reconfigures_without_duplicate_handlers(
    tmp_path, isolated_logging
):
    handler = configure_logging(
        "jobs", log_dir=tmp_path, secrets=['a"b\\c'], level="INFO"
    )
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 5
    handler.maxBytes = 250
    for _ in range(8):
        log.info('a"b\\c', extra={"event": "test.rotation"})
    assert (tmp_path / "jobs.log.1").exists()
    configure_logging("jobs", log_dir=tmp_path, level="INFO")
    log.info("One", extra={"event": "test.single"})
    log.debug("Hidden", extra={"event": "test.debug"})
    explicit = logging.getLogger("test.explicit_debug")
    explicit.setLevel(logging.DEBUG)
    try:
        explicit.debug("Hidden too", extra={"event": "test.debug"})
    finally:
        explicit.setLevel(logging.NOTSET)
    rows = [
        json.loads(line) for line in (tmp_path / "jobs.log").read_text().splitlines()
    ]
    assert sum(row["event"] == "test.single" for row in rows) == 1
    assert not any(row["event"] == "test.debug" for row in rows)
    assert 'a"b\\c' not in (tmp_path / "jobs.log.1").read_text()
    assert logging.getLogger("uvicorn.access").disabled
    configure_logging("web", log_dir=tmp_path)
    log.info("Web", extra={"event": "test.web"})
    assert json.loads((tmp_path / "web.log").read_text())["event"] == "test.web"


def test_retries_warn_only_when_retrying_and_never_include_exception_message(json_logs):
    attempts = 0
    sleeps = []

    def flaky():
        nonlocal attempts
        attempts += 1
        raise ValueError(
            "private listening data https://example.invalid/?api_key=hidden"
        )

    with pytest.raises(ValueError):
        retry_call(
            flaky,
            retry_on=ValueError,
            max_attempts=3,
            sleep=sleeps.append,
            rng=lambda: 1,
        )
    rows = records(json_logs)
    assert attempts == 3
    assert sleeps == [0.5, 1]
    assert [row["attempt"] for row in rows] == [1, 2]
    assert all(
        row["level"] == "WARNING" and row["exception_type"] == "ValueError"
        for row in rows
    )
    assert "private listening" not in json_logs.getvalue()
    assert "example.invalid" not in json_logs.getvalue()


def test_parse_page_summarizes_200_bad_rows_without_logging_listening_data(json_logs):
    payload = {
        "recenttracks": {
            "@attr": {"page": "2", "totalPages": "2"},
            "track": [
                {
                    "name": "",
                    "artist": {"#text": "private artist"},
                    "date": {"uts": "100"},
                }
            ]
            * 200,
        }
    }
    result = parse_page(payload, "private-user", 2)
    assert result.skipped == 200
    assert result.scrobbles == []
    assert len(records(json_logs)) == 1
    row = records(json_logs)[0]
    assert row["event"] == "scrobble.skipped"
    assert row["page"] == 2
    assert row["skipped"] == 200
    assert row["where"] == "name (string_too_short)"
    assert "private artist" not in json_logs.getvalue()
    assert "private-user" not in json_logs.getvalue()
