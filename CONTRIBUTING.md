# Contributing to Wrapped

Submit focused pull requests with clear behavior, rationale, and validation. Follow the existing module boundaries and include tests for new provider behavior.

Start with the [README](README.md), [development guide](docs/development.md), and [product decisions](docs/product-decisions.md). Spotify and Apple Music contributors should also read the [integration handoff](docs/provider-integration-handoff.md).

## Scope

- The provider contributor owns Spotify/Apple capability research, proposed adapter contracts, isolated clients/mappers/auth support, and their tests in separate PRs.
- Changes to shared models, migrations, sync, job error classification, settings, authentication routes, or analytics definitions need an agreed design in the PR before implementation is merged.
- Research and isolated adapters can progress now. Provider selection in the live application and production rollout remain later, coordinated integration work. A provider can legitimately finish research as unsupported or unsuitable.

## Branches and pull requests

Use a separate clone or worktree for each contribution. Start from the current target branch, normally `main`:

```sh
git fetch origin
git switch -c docs/provider-capabilities origin/main
```

Use descriptive branches such as `docs/provider-capabilities`, `feat/spotify-client`, `feat/apple-auth`, or `test/spotify-pagination`. Keep one reviewable outcome per PR. Include the tests that demonstrate a client or parser change in the same PR; do not postpone all testing to a final integration PR.

Before opening a PR:

```sh
uv sync --extra dev
uv run ruff check .
uv run mypy wrapped
uv run pytest -q
git diff --check
git status --short
git diff --cached --stat
```

Stage explicit paths and inspect the staged diff locally. Do not use `git add .` with private fixtures or unrelated scratch files present. Avoid pasting staged private contents into chat or PR descriptions. Commit messages should describe the resulting behavior, for example `Handle Spotify token expiry without retry loops`.

Push the feature branch and open a PR against `main`, or the agreed target branch. Fork-based contributions should target the upstream repository. Require maintainer review before merging. The GitHub Actions workflow runs on pushes and PRs; report check results and resolve failures without disabling checks.

## PR description

Use this structure in the PR description:

```text
Problem and resulting behavior
- What concrete case changes, and what the user/service now does.

Design
- Responsibilities, error handling, and any shared contract changes.
- Why this approach fits the existing code.

Validation
- Exact checks run and outcomes.
- Offline cases covered; any consenting live checks and their limits.

Compatibility and rollout
- Schema/config changes, migration and rollback implications.
- Whether the provider remains isolated or becomes selectable.
- Open limitations, policy/access questions, and follow-up work.
```

Link official provider evidence for behavior that is not obvious from a fixture. State unknowns directly. A successful API request is not proof of a complete event ledger.

## Code quality expectations

- Python 3.12+, typed public function signatures, small explicit data structures, and descriptive names.
- Follow local module patterns. Use Pydantic at untrusted-data boundaries; use dataclasses for calculated results where appropriate.
- Preserve original display values; use `core.normalize.key()` for the current comparison policy. Do not introduce a second normalizer.
- Keep HTTP/auth/paging in integrations, transactions/workflows in services, calculations in core, and presentation in entrypoints/renderers.
- Inject HTTP sessions, sleep functions, clocks, and randomness where behavior needs controlled testing. Avoid real sleeps or network in tests.
- Catch expected exceptions at the responsible boundary. Never turn a failure into a plausible empty success, and do not retry permanent failures unchanged.
- Use static, sanitized exception messages and stable logging events. Do not configure logging from libraries.
- Close responses and resources deterministically. Keep network work outside SQLite write transactions.
- Keep migrations numbered and additive; do not edit an already applied migration. Register new migration files in `db/store.py` and test upgrades with synthetic existing data.
- Avoid unrelated renames, formatting sweeps, new infrastructure, or dependency changes. Explain a new dependency and its maintenance/security tradeoff when genuinely necessary.
- Tests should establish behavior and failure guarantees, not merely repeat implementation details. All normal CI tests run offline.

## Privacy when sharing work

Use synthetic fixtures under `tests/fixtures/<provider>/`. Store private captures under the ignored `scripts/fixtures/` directory and verify ignore coverage before staging files. Raw captures must not appear in commits or PRs.

Do not include tokens, authorization codes, cookies, private keys, personal email/chat/account IDs, full request URLs, or raw listening history in screenshots, issue descriptions, logs, fixtures, or AI prompts. Removing one token is not enough to sanitize an entire response. Use obviously fictional data while preserving the shapes and edge cases being tested.
