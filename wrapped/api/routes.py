from __future__ import annotations

import logging
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from wrapped.core.config import Settings
from wrapped.db.store import connect
from wrapped.services.logview import read_logs

log = logging.getLogger(__name__)
_basic = HTTPBasic()
_templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def require_owner(
    request: Request, credentials: Annotated[HTTPBasicCredentials, Depends(_basic)]
) -> None:
    settings: Settings = request.app.state.settings
    username_ok = secrets.compare_digest(
        credentials.username.encode(), settings.owner_username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), settings.owner_password.encode()
    )
    if not (
        username_ok
        and password_ok
        and settings.owner_username
        and settings.owner_password
    ):
        raise HTTPException(
            401, "Owner login required", headers={"WWW-Authenticate": "Basic"}
        )


router = APIRouter(dependencies=[Depends(require_owner)])


def _run_data(settings: Settings) -> tuple[list[dict], dict]:
    try:
        with closing(connect(settings.database_path)) as db:
            runs = [
                dict(row)
                for row in db.execute(
                    "SELECT id, user_id, kind, started_at, finished_at, pages, fetched, inserted, status, error "
                    "FROM runs ORDER BY id DESC LIMIT 100"
                )
            ]
            health = dict(
                db.execute(
                    "SELECT COUNT(*) AS total_runs, "
                    "COALESCE(SUM(status='running'), 0) AS running, "
                    "COALESCE(SUM(status='failed' AND started_at >= unixepoch()-604800), 0) AS failures_7d "
                    "FROM runs"
                ).fetchone()
            )
        return runs, health
    except sqlite3.Error:
        log.critical(
            "Dashboard database unavailable", extra={"event": "database.unavailable"}
        )
        raise HTTPException(503, "Database unavailable") from None


@router.get("/", response_class=HTMLResponse)
@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    runs, health = _run_data(request.app.state.settings)
    return HTMLResponse(
        _templates.get_template("runs.html").render(runs=runs, health=health),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/health")
def health(request: Request) -> dict:
    _, summary = _run_data(request.app.state.settings)
    return {"status": "ok", **summary}


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    source: Literal["web", "jobs"] = "jobs",
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    level: Literal["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None,
    job: Annotated[str | None, Query(max_length=64)] = None,
    user: Annotated[str | None, Query(max_length=128)] = None,
    run_id: Annotated[str | None, Query(max_length=128)] = None,
) -> HTMLResponse:
    try:
        records = read_logs(
            request.app.state.settings.log_dir,
            source=source,
            limit=limit,
            level=level or None,
            job=job or None,
            user=user or None,
            run_id=run_id or None,
        )
    except (OSError, ValueError):
        log.warning("Log source unavailable", extra={"event": "logview.unavailable"})
        raise HTTPException(503, "Log source unavailable") from None
    return HTMLResponse(
        _templates.get_template("logs.html").render(
            records=records,
            source=source,
            limit=limit,
            level=level,
            job=job,
            user=user,
            run_id=run_id,
        ),
        headers={"Cache-Control": "no-store"},
    )
