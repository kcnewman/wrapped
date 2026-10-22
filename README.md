# Wrapped

A personal listening wrap from Last.fm scrobbles.

## Run locally

```sh
uv sync --extra dev
cp .env.example .env
# Set OWNER_USERNAME and OWNER_PASSWORD in .env before starting the dashboard.
uv run wrapped check
uv run uvicorn wrapped.api.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

The owner login protects `/`, `/runs`, `/logs`, and `/health` using HTTP Basic authentication. Use the loopback address through an SSH tunnel, or put a TLS reverse proxy in front of it. API docs are disabled. There are no mutation routes yet.

## Logs, run records, and alerts

`configure_logging()` runs only at CLI entry and ASGI startup. Library code only calls `logging.getLogger(__name__)`. Logs are JSON lines with UTC timestamps, levels, logger names, stable event names, and `job`, `run_id`, and `user` context. `user` is the internal registry ID. Default level is INFO; DEBUG is opt-in with `LOG_LEVEL=DEBUG`.

- INFO: job start/finish and counts.
- WARNING: retries, skipped-row page summaries, and alert delivery trouble.
- ERROR: a failed job.
- CRITICAL: rejected Last.fm credentials or an unusable database.

Files live under `WRAPPED_DATA_DIR/logs`: `web.log` and `jobs.log`, each rotating at 5 MiB with five backups. Run exactly one uvicorn worker. All cron invocations must use the same data volume and `jobs.lock`; the CLI takes its nonblocking `flock` before constructing its file handler. An overlapping invocation exits successfully with a skip message and creates no run record. Never remove the lock file while the app is running. A web-triggered job must use the same lock and stays in `web.log` because it runs in the web process.

The `/logs` viewer and `wrapped logs` read only those two active files. They inspect the last N physical lines (maximum 2,000), skip malformed, oversized, and unterminated entries, and support exact level, job, user, and run filters. The scan is bounded to 10 MiB. Archived rotation files are available over SSH. Templates autoescape; JSON displayed in HTML also escapes HTML characters.

```sh
uv run wrapped logs --source jobs --level WARNING --job sync --user 4 --run-id 7
```

`/runs` and `/health` read SQLite's `runs` table, independently of log contents. Run errors and alert messages contain exception types, never exception messages. Set both `TELEGRAM_TOKEN` and `TELEGRAM_OWNER_CHAT_ID` to enable owner failure alerts. An alert outage produces a warning and preserves the original job failure. Missing alert configuration produces a warning on a failed job.

API keys, bot tokens, SMTP credentials, the configured owner chat ID, and the owner password are registered for exact-value redaction at startup, including exception text. Redaction is a safety net: application call sites must never log artist, track, or album names, full URLs, email addresses, or chat IDs. Use static messages and operational fields; arbitrary extra fields and domain objects are not serialized.

## Using the job runner

Use a dedicated run-record connection, separate from the transaction that writes application data. The body commits or rolls back its application work before returning. The context manager acquires the shared job lock, writes the running row, adds context to all nested library logs, finalizes counts/status, and sends a Telegram alert if the body fails. It reraises the original exception.

```python
from contextlib import closing
from wrapped.db.store import connect
from wrapped.services.alerts import TelegramAlert
from wrapped.services.jobs import job

with closing(connect(settings.database_path)) as runs_db:
    with job(
        "sync", db=runs_db, lock_path=settings.job_lock_path, user_id=user.id,
        alert=TelegramAlert(settings.telegram_token, settings.telegram_owner_chat_id),
    ) as run:
        # Fetch and commit using a separate application-data connection here.
        run.pages = result.pages
        run.fetched = len(result.scrobbles)
        run.inserted = inserted_count
```

For new CLI jobs, retain the CLI's outer lock through logging setup, database startup, and the final record/alert; pass its `held_lock` into `job()` to avoid acquiring the same lock twice. `wrapped check` demonstrates this with an actual SQLite quick check. Interrupted processes may leave a `running` record; this change does not automatically classify stale runs.

## Verify

```sh
uv run ruff check .
uv run mypy wrapped
uv run pytest -q
```

Tests use temporary files/databases and mocked HTTP; they do not call Last.fm or Telegram.
