from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI

from wrapped.api.routes import router
from wrapped.core.config import Settings, load_settings
from wrapped.core.logging import configure_logging
from wrapped.db.store import connect, initialize

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else load_settings()
        configure_logging(
            "web",
            log_dir=config.log_dir,
            secrets=config.redactions,
            level=config.log_level,
        )
        app.state.settings = config
        try:
            if not config.owner_username or not config.owner_password:
                raise ValueError("Owner login must be configured")
            with closing(connect(config.database_path)) as db:
                initialize(db)
        except (ValueError, OSError, sqlite3.Error) as exc:
            log.critical(
                "Web startup failed",
                extra={
                    "event": "web.startup_failed",
                    "exception_type": type(exc).__name__,
                },
            )
            raise RuntimeError(
                "Web startup failed; check owner login and database configuration"
            ) from None
        log.info("Web application started", extra={"event": "web.started"})
        try:
            yield
        finally:
            log.info("Web application stopped", extra={"event": "web.stopped"})

    return FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        routes=router.routes,
    )


app = create_app()
