# Development and operations

Local setup, collection commands, operational logging, and transaction requirements. See [CONTRIBUTING](../CONTRIBUTING.md) for code and PR requirements.

## Local setup

Use Python 3.12 or newer and `uv`. From the repository root:

```sh
uv sync --extra dev
test -e .env || cp .env.example .env
```

Configure `.env`:

- `LASTFM_API_KEY` for live Last.fm enrollment and collection.
- `OWNER_USERNAME` and `OWNER_PASSWORD` before starting the dashboard.
- Both `TELEGRAM_TOKEN` and `TELEGRAM_OWNER_CHAT_ID` to enable owner failure alerts.
- `WRAPPED_DATA_DIR` to choose the data directory; the default is `./data`.
- `LOG_LEVEL` if needed; the production default is `INFO`.

The SMTP and LLM entries in `.env.example` anticipate later work; their presence does not mean email delivery or narration is implemented. Spotify and Apple credentials are not configured by the current application.

Never commit `.env`, databases, tokens, or raw captures. Public test fixtures must be synthetic or carefully sanitized. Provider research uses a separate app/account and consenting test users, not production credentials.

## Initialize and inspect the service

```sh
uv run wrapped check
uv run uvicorn wrapped.api.app:app --host 127.0.0.1 --port 8080 --workers 1 --no-access-log
```

`check` initializes pending SQLite migrations and records a database quick-check job. It does not fetch listening history. The database is `WRAPPED_DATA_DIR/wrapped.db`.

The owner login protects `/`, `/runs`, `/logs`, and `/health` using HTTP Basic authentication. API docs are disabled. Use loopback through an SSH tunnel, or put a TLS reverse proxy in front of the app before exposing it. There are no mutation routes yet; future mutation routes need CSRF protection. Provider consent callbacks will need their own state-bound authorization design.

Run exactly one uvicorn worker. Docker and Compose files are placeholders, not a working deployment path yet.

## Enroll and collect from Last.fm

Replace the example username and display name with a consenting user's details:

```sh
uv run wrapped user add --user YOUR_LASTFM_USERNAME --name "Your name" --tz Africa/Accra
uv run wrapped sync --user YOUR_LASTFM_USERNAME
```

These commands contact Last.fm. Enrollment probes the account, creates the user, and assigns the current server timestamp as `history_from`. It does not import earlier listening.

Collection uses a 12-hour overlap bounded by enrollment and a five-minute settle lag. Immediately after enrollment, an empty or unsettled window is normal. Listen after joining, allow the play to reach Last.fm and settle, then sync again. A repeated fetch can have a positive fetched count and zero inserted rows because duplicate observations are ignored.

Do not modify enrollment timestamps or production checkpoints to manufacture a test case. Use isolated databases for controlled boundary and failure checks. A GUI SQLite browser can inspect `data/wrapped.db`; prefer read-only mode against a running instance, and use a SQLite-aware backup for a stable copy rather than copying only the main file while WAL writes are active.

Run `uv run wrapped --help` or a subcommand's `--help` for available options. A report/dry-run command is not yet implemented.

## Run records, logs, and alerts

- **Run records:** the SQLite `runs` table says whether a job worked and how much it did. `/runs` and `/health` read this table, independently of log text.
- **Application logs:** JSON-lines files show ordered operational events for the dashboard log viewer and SSH troubleshooting.
- **Alerts:** the job runner sends owner Telegram messages on failure. Logging handlers never make network calls.

`configure_logging()` runs only at CLI entry and ASGI startup. Libraries call `logging.getLogger(__name__)` without configuring handlers. Records carry UTC timestamps, stable event names, and context for `job`, `run_id`, and `user`; `user` is the internal registry ID.

Level policy:

- `INFO`: job lifecycle and counts.
- `WARNING`: recoverable anomalies, retries, skipped-row page summaries, and alert delivery trouble.
- `ERROR`: a failed job.
- `CRITICAL`: the application cannot operate, such as rejected application credentials or an unusable database.
- `DEBUG`: opt-in with `LOG_LEVEL=DEBUG`, off in production; privacy rules still apply.

Files live under `WRAPPED_DATA_DIR/logs`: `web.log` and `jobs.log`, each rotating at 5 MiB with five backups. All scheduled writer invocations must share the data volume and `jobs.lock`. The CLI takes a nonblocking `flock` before constructing its log handler; an overlapping invocation exits successfully with a skip message and creates no run record. Never remove the lock file while the app is running. Future web-triggered jobs must use the same lock and stay in `web.log` because they run in the web process.

The `/logs` viewer and `wrapped logs` read only those two active files. They inspect the last N physical lines, at most 2,000, within a bounded 10 MiB scan; malformed, oversized, and unterminated entries are skipped. Exact level, job, user, and run filters are supported. Rotation archives remain available over SSH. Templates autoescape; JSON displayed in HTML also escapes HTML characters.

```sh
uv run wrapped logs --source jobs --level WARNING --job sync --user 4 --run-id 7
```

Run errors and alerts contain exception types rather than provider exception messages. An alert outage logs a warning and preserves the original failure. Missing alert configuration also produces a warning on a failed job.

API keys, bot tokens, SMTP credentials, the configured owner chat ID, and owner password are registered for exact-value redaction at startup, including exception text. Redaction is a safety net. Never log artist, track, or album names, full URLs, email addresses, chat IDs, raw payloads, or credentials. Use static messages and operational fields. Arbitrary extra fields and domain objects are not serialized; new structured fields require an explicit formatter change and review. Future provider credentials need equivalent redaction and lifecycle handling.

## Shared service actions and transactions

`wrapped/services/services.py` exposes `run_enrollment()` and `run_sync()`. These actions manage resource lifetimes and invoke the job runner. CLI commands and dashboard routes call the same actions.

For data-changing jobs:

1. Hold the shared lock through startup, logging, and job completion. A CLI caller passes its existing `held_lock` into the service and job runner.
2. Use a dedicated run-record connection. Commit the initial `running` record separately so failed attempts remain visible.
3. Fetch provider data before the application-data transaction. Never hold a SQLite write transaction during HTTP or retry sleeps.
4. Write events, the checkpoint, and successful run status together. Current services pass a `before_commit` callback to `sync_user()` or `enroll_user()`; it calls `run.stage_success(data_db)` on that transaction's connection.
5. On rollback, record failure separately without claiming committed inserts. Do not associate a failed enrollment with a user row that rolled back.
6. Preserve committed success if post-commit handling fails. `JobCompletionError` distinguishes a committed-but-troubled or unconfirmed outcome; do not report it as an ordinary rollback.

Successful run status must commit with the application data. The job runner reraises ordinary failures and raises `JobCompletionError` for post-commit errors or unconfirmed outcomes. Interrupted processes can leave a `running` row; automatic stale-run reconciliation is not implemented.

## Checks

```sh
uv run ruff check .
uv run mypy wrapped
uv run pytest -q
```

These match the checks configured in `.github/workflows/ci.yml`; CI currently installs `.[dev]` with pip on Python 3.12. Tests use temporary files/databases and fake HTTP. They must not call Last.fm, Spotify, Apple, or Telegram.

The existing suite mainly covers operational tooling. Ingestion and reporting regression coverage is incomplete. Provider changes require offline automated tests; see the [integration test requirements](provider-integration-handoff.md#required-tests).

For a database-only smoke check that leaves your regular data directory alone:

```sh
WRAPPED_DATA_DIR=/tmp/wrapped-smoke uv run wrapped check
```

Use a fresh temporary directory when you need a clean database. Live provider experiments are separate, opt-in manual checks; record what they prove and what remains unknown. Passing offline tests does not establish live access, history completeness, or permission to use the data.
