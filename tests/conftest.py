import io
import logging
import sqlite3

import pytest

from wrapped.core.logging import ContextFilter, JsonFormatter, RedactionFilter
from wrapped.db.store import initialize


@pytest.fixture
def json_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    redactor = RedactionFilter(["test-api-secret"])
    handler.addFilter(redactor)
    handler.setFormatter(JsonFormatter(redactor))
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)
    root.setLevel(level)
    handler.close()


@pytest.fixture
def isolated_logging():
    """Entrypoint configuration must not close pytest's capture handlers."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers = []
    names = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "urllib3",
        "requests",
    )
    states = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
        )
        for name in names
    }
    for name in names:
        logging.getLogger(name).handlers = []
    yield
    for handler in root.handlers[:]:
        handler.close()
    root.handlers = handlers
    root.setLevel(level)
    for name, (old_handlers, old_level, propagate, disabled) in states.items():
        logger = logging.getLogger(name)
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate, logger.disabled = propagate, disabled


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    initialize(connection)
    yield connection
    connection.close()
