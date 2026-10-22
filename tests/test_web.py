import json
import logging
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from wrapped.api.app import create_app
from wrapped.cli import main
from wrapped.core.config import Settings
from wrapped.db.store import connect
from wrapped.services.jobs import job_lock

AUTH = ("owner", "owner-test-secret")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        owner_username=AUTH[0],
        owner_password=AUTH[1],
        lastfm_api_key="api-test-secret",
        telegram_token="bot-test-secret",
        smtp_password="smtp-test-secret",
    )


@pytest.mark.parametrize("path", ["/", "/runs", "/logs", "/health"])
def test_every_route_requires_owner_login(path, settings, isolated_logging):
    with TestClient(create_app(settings)) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, auth=("owner", "wrong")).status_code == 401
        assert client.get(path, auth=AUTH).status_code == 200


def test_web_escapes_untrusted_logs_and_filters_without_exposing_secrets(
    settings, isolated_logging
):
    with TestClient(create_app(settings)) as client:
        with job_lock(settings.job_lock_path):
            from wrapped.core.logging import log_context

            with log_context(job="sync", user=4, run_id=7):
                logging.getLogger("test").warning(
                    '<script>alert("xss")</script> api-test-secret bot-test-secret smtp-test-secret',
                    extra={"event": "test.untrusted"},
                )
        response = client.get(
            "/logs",
            params={
                "source": "web",
                "job": "sync",
                "user": "4",
                "run_id": "7",
                "level": "WARNING",
            },
            auth=AUTH,
        )
        assert response.status_code == 200
        assert "test.untrusted" in response.text
        assert '<script>alert("xss")</script>' not in response.text
        assert "\\u003cscript\\u003e" in response.text
        assert "[REDACTED]" in response.text
        for secret in settings.redactions:
            if secret:
                assert secret not in response.text
        assert (
            client.get(
                "/logs",
                params={"level": "", "job": "", "user": "", "run_id": ""},
                auth=AUTH,
            ).status_code
            == 200
        )
        assert (
            client.get("/logs", params={"source": "../../.env"}, auth=AUTH).status_code
            == 422
        )
        assert (
            client.get("/logs", params={"limit": "2001"}, auth=AUTH).status_code == 422
        )


def test_health_reads_runs_table_not_application_logs(settings, isolated_logging):
    with TestClient(create_app(settings)) as client:
        db = connect(settings.database_path)
        try:
            with db:
                db.execute(
                    "INSERT INTO runs (kind, started_at, status) VALUES ('sync', unixepoch(), 'failed')"
                )
        finally:
            db.close()
        # Log contents cannot invent or remove run records.
        (settings.log_dir / "jobs.log").write_text('{"status":"success"}\n')
        health = client.get("/health", auth=AUTH).json()
        assert health["total_runs"] == 1
        assert health["failures_7d"] == 1
        page = client.get("/runs", auth=AUTH)
        assert "failed" in page.text


def test_missing_owner_configuration_fails_closed(tmp_path, isolated_logging):
    with (
        pytest.raises(RuntimeError, match="Owner|owner"),
        TestClient(create_app(Settings(data_dir=tmp_path))),
    ):
        pytest.fail("Web app started without an owner login")


def test_imports_do_not_configure_logging_or_create_files(tmp_path):
    code = """
import logging
before = logging.getLogger().handlers[:]
import wrapped.cli
import wrapped.api.app
import wrapped.integrations.lastfm.schema
assert logging.getLogger().handlers == before
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_cli_check_and_overlap(settings, isolated_logging, capsys):
    with patch("wrapped.cli.load_settings", return_value=settings):
        assert main(["check"]) == 0
        db = connect(settings.database_path)
        try:
            assert db.execute("SELECT status FROM runs").fetchone()[0] == "success"
        finally:
            db.close()
        with job_lock(settings.job_lock_path):
            assert main(["check"]) == 0
        assert "already running" in capsys.readouterr().out
        assert main(["logs", "--job", "check"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert [json.loads(line)["event"] for line in lines] == [
            "job.started",
            "job.finished",
        ]
