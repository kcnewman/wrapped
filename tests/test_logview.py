import json

import pytest

from wrapped.services.logview import MAX_LINE_BYTES, read_logs


def entry(**values):
    return {
        "ts": "2026-10-16T11:45:02Z",
        "level": "INFO",
        "logger": "test",
        "event": "job.started",
        "job": "sync",
        "user": 4,
        "run_id": 7,
        **values,
    }


def test_tolerant_tail_skips_malformed_and_partial_lines_and_filters(tmp_path):
    lines = [
        json.dumps(entry(run_id=1)),
        "not json",
        "[]",
        "{}",
        "\xff",
        json.dumps(entry(level="WARNING")),
        json.dumps(entry(job="report")),
        json.dumps(entry()),
    ]
    (tmp_path / "jobs.log").write_bytes(
        ("\n".join(lines) + "\n" + json.dumps(entry(event="partial.write"))).encode()
    )
    assert read_logs(tmp_path, limit=2) == [entry(job="report"), entry()]
    assert read_logs(tmp_path, level="WARNING", job="sync", user="4", run_id="7") == [
        entry(level="WARNING")
    ]
    assert read_logs(tmp_path, job="other") == []


def test_tail_handles_missing_empty_and_oversized_lines(tmp_path):
    assert read_logs(tmp_path) == []
    path = tmp_path / "jobs.log"
    path.write_bytes(b"")
    assert read_logs(tmp_path) == []
    path.write_bytes(
        b"x" * (MAX_LINE_BYTES + 1) + b"\n" + json.dumps(entry()).encode() + b"\n"
    )
    assert read_logs(tmp_path) == [entry()]


@pytest.mark.parametrize(
    "source", ["../jobs.log", "/etc/passwd", "jobs.log", "web.log.1"]
)
def test_only_fixed_sources_are_allowed(tmp_path, source):
    with pytest.raises(ValueError):
        read_logs(tmp_path, source=source)


def test_refuses_symlink(tmp_path):
    (tmp_path / "jobs.log").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        read_logs(tmp_path)
