import json
import logging
import sqlite3
import subprocess
import sys

import pytest

from wrapped.core.logging import log_context
from wrapped.integrations.lastfm.errors import LastfmCredentialsError
from wrapped.services.jobs import JobAlreadyRunning, job, job_lock


def test_success_records_counts_and_context_and_releases_lock(db, tmp_path, json_logs):
    alerts = []
    with log_context(job="outer", user=99):
        with job(
            "sync",
            db=db,
            lock_path=tmp_path / "jobs.lock",
            user_id=4,
            alert=alerts.append,
        ) as run:
            assert db.execute("SELECT status FROM runs").fetchone()[0] == "running"
            run.pages, run.fetched, run.inserted = 2, 200, 180
            logging.getLogger(__name__).info("Work", extra={"event": "sync.counted"})
        logging.getLogger(__name__).info("Outside", extra={"event": "test.outside"})
    row = dict(db.execute("SELECT * FROM runs").fetchone())
    assert row["status"] == "success"
    assert (row["pages"], row["fetched"], row["inserted"]) == (2, 200, 180)
    assert row["finished_at"] >= row["started_at"]
    assert not alerts
    entries = [json.loads(line) for line in json_logs.getvalue().splitlines()]
    assert all(row["run_id"] == run.id and row["user"] == 4 for row in entries[:-1])
    assert entries[-1]["job"] == "outer"
    assert entries[-1]["user"] == 99
    with job_lock(tmp_path / "jobs.lock"):
        pass


@pytest.mark.parametrize(
    "error,level",
    [
        (RuntimeError("private artist and https://secret.invalid/?key=bad"), "ERROR"),
        (LastfmCredentialsError("private credential text"), "CRITICAL"),
        (sqlite3.DatabaseError("private database text"), "CRITICAL"),
    ],
)
def test_failure_records_safe_error_alerts_and_reraises(
    db, tmp_path, json_logs, error, level
):
    alerts = []
    with (
        pytest.raises(type(error)) as raised,
        job(
            "sync", db=db, lock_path=tmp_path / "jobs.lock", alert=alerts.append
        ) as run,
    ):
        run.pages = 3
        raise error
    assert raised.value is error
    row = dict(db.execute("SELECT * FROM runs").fetchone())
    assert row["status"] == "failed"
    assert row["error"] == type(error).__name__
    assert row["pages"] == 3
    assert len(alerts) == 1
    assert "private" not in alerts[0]
    assert "private" not in json_logs.getvalue()
    failure = [json.loads(line) for line in json_logs.getvalue().splitlines()][-1]
    assert failure["event"] == "job.failed"
    assert failure["level"] == level


def test_alert_failure_does_not_mask_original_failure(db, tmp_path, json_logs):
    def broken_alert(_):
        raise ValueError("private bot token")

    with (
        pytest.raises(RuntimeError, match="original"),
        job("sync", db=db, lock_path=tmp_path / "jobs.lock", alert=broken_alert),
    ):
        raise RuntimeError("original")
    assert db.execute("SELECT status FROM runs").fetchone()[0] == "failed"
    assert "alert.failed" in json_logs.getvalue()
    assert "private bot token" not in json_logs.getvalue()


def test_database_failure_before_run_is_critical_and_alerted(tmp_path, json_logs):
    db = sqlite3.connect(":memory:")
    alerts = []
    try:
        with (
            pytest.raises(sqlite3.OperationalError),
            job("sync", db=db, lock_path=tmp_path / "jobs.lock", alert=alerts.append),
        ):
            pytest.fail("Missing runs table must not execute the job")
        assert len(alerts) == 1
        row = json.loads(json_logs.getvalue().splitlines()[-1])
        assert row["level"] == "CRITICAL"
        assert row["run_id"] is None
    finally:
        db.close()


def test_lock_excludes_other_process_and_can_be_reused(tmp_path):
    path = tmp_path / "jobs.lock"
    code = """
import sys
from pathlib import Path
from wrapped.services.jobs import JobAlreadyRunning, job_lock
try:
    with job_lock(Path(sys.argv[1])):
        print('acquired')
except JobAlreadyRunning:
    print('locked')
"""
    with job_lock(path):
        child = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert child.stdout.strip() == "locked"
        with pytest.raises(JobAlreadyRunning), job_lock(path):
            pytest.fail("Overlapping lock acquired")
    child = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert child.stdout.strip() == "acquired"


def test_released_lock_token_cannot_bypass_lock(db, tmp_path):
    path = tmp_path / "jobs.lock"
    with job_lock(path) as token:
        pass
    with (
        pytest.raises(ValueError, match="Job lock"),
        job("sync", db=db, lock_path=path, held_lock=token),
    ):
        pytest.fail("Released token was accepted")
