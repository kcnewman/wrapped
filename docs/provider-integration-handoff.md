# Spotify and Apple Music integration handoff

Status: capability research and isolated adapter development.

## Objective

Evaluate Spotify and Apple Music as sources of individual listening events. Build tested adapters for capabilities that meet the product's data, reliability, and usage requirements.

Start with a capability assessment for each provider. Develop adapters separately from application wiring; production enablement requires integration testing and review. Document unsupported capabilities and blockers explicitly.

Related documentation: [product overview](../README.md), [development guide](development.md), [contribution requirements](../CONTRIBUTING.md), and [metric definitions](product-decisions.md).

## Scope

Wrapped generates monthly listening reports for enrolled users. An administrator manages the service through a dashboard; a CLI supports scheduling and troubleshooting. Recipients receive reports through Telegram or email without dashboard accounts. Annual reports, narration, and future visual formats use the same calculated facts.

Provider work proceeds independently of P4 analytics. See the [roadmap](../README.md#roadmap) for overall implementation status.

**Deliverables:** capability assessments, research tooling, authentication design, HTTP clients, response models and mappers, provider-specific errors, offline fixtures and tests, and an application integration proposal.

**Shared changes requiring design review:** domain models, provider-account storage, migrations, checkpoints, sync/job services, logging fields, settings, callback routes, and metric definitions. Submit the proposed contract and compatibility impact before implementation is merged.

**Out of scope:** analytics, narration, video generation, report delivery, public signup, payments, recommendations, playback control, catalog scraping, pre-enrollment imports, automatic provider fallback, simultaneous source merging, and infrastructure replacement. Provider consent flows must remain separate from administrator authentication.

## Required behavior

1. **Enrollment is the lower bound.** `history_from` is assigned by the server and never moved earlier. Discard pre-enrollment observations even when returned unexpectedly. Collect immediately; do not wait for report eligibility.
2. **Repeated plays survive; repeated fetches do not duplicate.** A content ID identifies a song, not one listening event. Different play times must remain separate. Overlap, retries, and repeated pages must be safe.
3. **Fetch failure must not advance the checkpoint.** Events, checkpoint advancement, and successful run outcome commit together. Never return an empty success after an auth, transport, protocol, or pagination failure.
4. **Coverage must be honest.** A successful response does not establish that every play in a requested month or outage window was available. A retention gap needs an explicit outcome and recovery policy.
5. **Report rules remain unchanged.** Local calendar windows use UTC half-open boundaries `[start, end)`. Require 15 elapsed enrollment days within the period, label eligible partial periods, and suppress ineligible reports/deliveries. Quiet eligible periods below 20 plays use deterministic text; comparisons require at least 50 previous-period plays.
6. **Missing measurements remain unknown.** Listening duration, skip/completion rate, worldwide percentiles, and mood/age scores require supporting data. See decisions D06–D10.
7. **One explicitly selected primary source per user.** No automatic fallback or parallel-source merging. Source switching and coverage continuity need a separately agreed policy.

## Existing implementation

Relevant modules:

- `wrapped/integrations/lastfm/client.py`: synchronous requests client; input checks, timeout, response classification, bounded retries, pagination, and `RecentFetch` result.
- `wrapped/integrations/lastfm/schema.py`: Pydantic response validation, normalization of provider quirks, now-playing exclusion, skipped-row accounting, and one warning per affected page.
- `wrapped/integrations/lastfm/errors.py`: transient/permanent and more specific exceptions. HTTP status and numeric provider code are safe attributes; raw response messages are not copied.
- `wrapped/core/retry.py`: injectable sleep/randomness with exponential jitter and bounded attempts. It does not currently implement provider `Retry-After` handling.
- `wrapped/core/models.py`: `Scrobble`, which currently includes a Last.fm username, and `Event`, the normalized analytics input. `Event` is not a provider connection or a lossless provider-observation schema.
- `wrapped/core/normalize.py`: NFKC, whitespace collapse, and casefold comparison keys. Original display strings remain available.
- `wrapped/services/sync.py`: Last.fm-specific `to_row()` and `sync_user()`; fetches before opening a write transaction, filters bounds, inserts idempotently, advances checkpoint, and invokes a before-commit callback.
- `wrapped/services/services.py`: `run_enrollment()` and `run_sync()` resource orchestration shared by CLI and future web actions. Both currently instantiate Last.fm directly.
- `wrapped/services/users.py`: enrollment validation and the immutable join timestamp.
- `wrapped/services/jobs.py`: process lock, run records, log context, atomic success staging, failure alerting, and committed/uncertain-outcome handling. Critical credential classification currently explicitly names `LastfmCredentialsError`.
- `wrapped/db/store.py` and `wrapped/db/migrations/`: SQLite connection options and numbered migrations.
- `wrapped/core/config.py` and `wrapped/core/logging.py`: entrypoint-loaded settings, redaction registration, and an allowlist of serialized log fields.
- `wrapped/core/metrics.py`: pure analytics over normalized `Event` objects. It must not import provider clients.
- `wrapped/cli.py`, `wrapped/api/`: CLI adapters and administrator-authenticated pages. Ingestion logic belongs in services.
- `tests/conftest.py`: in-memory SQLite and log-capture fixtures. Existing tests primarily cover operational behavior.

Current coupling and limitations:

- Users currently store `lastfm_user` and `last_sync` directly.
- Events use `(user_id, uts, artist_key, track_key)` as their primary key, with integer-second timestamps and no provider provenance.
- Last.fm fetch bounds are currently inclusive; analytics bounds are half-open. A new contract must explicitly translate provider boundaries instead of conflating them.
- Last.fm's 12-hour overlap, five-minute settle lag, and planned six-hour schedule are not proven suitable for other providers.

## Deliverable 1: capability and permission assessments

Submit `docs/spotify-spike.md` and `docs/apple-music-spike.md` in the first PR. Separate observed behavior, documented guarantees, assumptions, and unresolved questions. Include dated official references and results from consenting test accounts. Use synthetic or sanitized examples.

For each provider establish:

- Account/app eligibility, developer access, costs/subscription requirements, tester limits, exact user permissions, and whether background server collection is supported.
- Authentication/token lifecycle: user consent, expiry, refresh or replacement, revoked access, reconnect, disconnect, and deletion requirements.
- Whether the endpoint yields individual plays or a list of recently encountered content. Can the same song appear twice? Are per-play timestamps supplied? What do they mean, with what precision and device coverage?
- Paging direction, cursor semantics, inclusive/exclusive boundaries, ordering, repeated/tied timestamps, moving history, and finite request limits. Is pagination stable while new plays arrive?
- Observable retention/recovery depth, delay, private/offline sessions, unavailable catalog items, and missed-history detection. Do not invent a retention guarantee from one sample.
- Available artist credits, stable content IDs, album IDs/credits, catalog duration, release-date precision, and nullable fields. Identify what cannot support current metrics.
- Rate limits versus account/app quotas, retry guidance, and error envelopes for each relevant endpoint. Document any behavior you could not trigger safely.
- Applicable storage, retention/deletion, attribution, metadata display, derived analytics, AI, and video/audio restrictions. List unresolved permissions explicitly, without claiming legal clearance.

Conclude each assessment with a recommendation: proceed; proceed with reduced scope; blocked pending access, permission, or evidence; or unsuitable as an event source. State the supporting evidence and unresolved dependencies. Playback-state polling must not be presented as a reliable event ledger.

### Spotify

The current [recently-played reference](https://developer.spotify.com/documentation/web-api/reference/get-recently-played) specifies `/me/player/recently-played`, user scope `user-read-recently-played`, up to 50 items per request, and mutually exclusive millisecond `after`/`before` cursors that exclude the cursor position. It exposes play timestamps, catalog track metadata, and nullable context. Validate recovery and boundary behavior; one page is not a monthly total.

[User authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization) is required for personal resources; client credentials alone cannot provide a user's history. Propose an authorization-code flow for the server deployment, including state binding and refresh behavior.

The [rate-limit guide](https://developer.spotify.com/documentation/web-api/concepts/rate-limits) describes 429 responses and `Retry-After` seconds. Distinguish a short rate limit from an exhausted app quota. The [quota-mode guide](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), checked 2026-11-01, currently lists a Premium requirement for the development-app owner, five authenticated users, and allowlisting. Recheck the actual registered app; these rules can change.

The [Developer Policy](https://developer.spotify.com/policy), especially III.6 and III.13–14, restricts audio/visual synchronization, derived listening/user analytics, and AI ingestion. Assess applicability and any required permissions for the proposed features. Aggregation alone does not establish permission. Document disconnect, deletion, and attribution obligations alongside any blockers.

Use synthetic fixtures for shared tests. Multiple artist credits must not multiply a play into several events. Catalog duration is not measured listening time, and a recently-played entry does not establish that 50% of a track was heard.

### Apple Music

Start with [MusicKit](https://developer.apple.com/musickit/), [user authentication](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit), [recently-played tracks](https://developer.apple.com/documentation/applemusicapi/get-v1-me-recent-played-tracks), and [recently-played resources](https://developer.apple.com/documentation/applemusicapi/get-recently-played-resources).

The event-history and authentication contracts require validation. Verify individual timestamps, repeated plays, cross-device coverage, pagination, retention, and unattended authentication using official documentation and consenting test accounts. Evaluate developer-token and user-authorization requirements independently of Spotify's token lifecycle.

An ordered recently-played list or device-specific last-played property is not sufficient evidence of a timestamped event ledger. If that is all the permitted API exposes, document the limitation and stop short of analytics ingestion.

## Deliverable 2: adapter contract

Define a shared boundary from the validated provider capabilities. The following describes the proposed flow; a shared interface is not yet implemented:

```text
Provider account + requested UTC window + provider checkpoint
    → adapter: authenticate, request, page, validate, map
    → batch: observations + counts + coverage + candidate checkpoint
    → service: enforce enrollment, deduplicate, commit
    → core Event projection: deterministic analytics
```

The proposal must define:

- **Observation:** provider, account reference, play timestamp and its meaning/precision, provider event ID if actually supplied, content/artist/album identifiers and display credits, and optional metadata with explicit units. Do not invent event IDs from a song ID alone.
- **Batch:** observations, page/fetched/skipped counts with precise meanings, requested and observable coverage, completion/gap status, and a candidate cursor/checkpoint. A cursor remains opaque unless documented otherwise.
- **Capabilities:** whether timestamped events exist, whether bounded historical recovery is possible, and which metadata is available. Unsupported operations have explicit outcomes, not empty lists.
- **Boundary semantics:** preferably a domain half-open window translated into each provider's actual request semantics, with handling for subsecond timestamps and ties. Do not truncate away information required for identity or paging.
- **Persistence responsibilities:** services own DB writes and checkpoints; adapters do not silently save progress. Specify when a candidate checkpoint is safe to commit.
- **Attribution:** preserve all credits in the proposed observation model, then choose a documented projection for current name-based metrics. Current Last.fm grouping uses artist credit strings, not resolved individual collaborators. Do not silently replace it or duplicate events.
- **Identity and provenance:** define provider-scoped deduplication and account separation. Preserve the existing Last.fm key for existing data; propose a migration when needed. Cross-provider matching and source switching remain separate design work.

Use typed results and a minimal interface, such as a `Protocol`, where supported by the validated requirements. Keep unsupported metadata optional. `Scrobble.username` currently represents a Last.fm username; other provider identities require an explicit model rather than reusing that field.

## Deliverable 3: provider adapter packages

Proposed locations, not files that already exist:

```text
wrapped/integrations/spotify/
    __init__.py     # intentional public exports
    client.py       # bounded HTTP requests and pagination
    schema.py       # provider response validation and mapping
    errors.py       # sanitized provider-specific exceptions
    auth.py         # only if the proven flow needs this separation

wrapped/integrations/apple_music/
    __init__.py
    client.py
    schema.py
    errors.py
    auth.py

tests/fixtures/spotify/        # synthetic or reviewed sanitized JSON
tests/fixtures/apple_music/
tests/test_spotify_client.py
tests/test_spotify_schema.py
tests/test_spotify_auth.py
tests/test_apple_music_client.py
tests/test_apple_music_schema.py
tests/test_apple_music_auth.py
```

Only create modules needed by viable behavior. Prefer the existing synchronous `requests` approach unless there is a concrete reason to differ. A native/browser MusicKit component, if required, needs an explicit proposal rather than an unrelated web-stack rewrite. Never run blocking provider calls directly on FastAPI's async event loop; later web orchestration must arrange appropriate execution without replacing the shared process lock with an in-process-only lock.

### Clients and authentication

- Inject the HTTP session, clock, and sleep/randomness where relevant. Document whether the caller or client owns the session; close every response, including JSON/validation failure paths.
- Validate inputs before network work. Use bounded connect/read timeouts, page limits, attempt counts, and a total retry/time budget. Stop repeated cursors and no-progress loops with a visible error.
- Authenticate only to fixed approved HTTPS origins. Disable unexpected redirects or validate each redirect before credentials are forwarded. Validate next-page URLs, scheme, host, port, and endpoint/path before sending tokens; do not blindly follow provider-supplied links.
- Validate the response envelope and per-play fields separately. Ignore extra provider fields where safe; reject missing structure needed to establish pagination or event meaning.
- Optional missing metadata stays missing. A malformed identity/timestamp must not silently become a fully covered successful window. Propose failing the batch or returning explicit incomplete coverage with a defined service policy. Last.fm's current counted-row-skip behavior is not a universal coverage guarantee.
- Keep app secrets and per-user tokens out of reprs, logs, fixtures, and exceptions. App configuration and per-user credential storage are different concerns; do not put every user's token into a single environment variable.
- Propose protected token/private-key storage, key ownership, token replacement, expiry, revoked consent, and deletion. Do not commit a token store or assume `.env` is sufficient for all users.
- For consent callbacks, bind a one-use, expiring state to the intended connection and initiating operation; reject mismatches/replays, avoid open redirects, and prevent cross-user linking. Use PKCE where appropriate to the selected flow. Keep token exchange server-side.
- Administrator authentication and recipient consent are separate flows. Use scoped account-linking authorization without sharing provider passwords or administrator credentials. Design callback exposure, HTTPS, route authorization, and CSRF/state handling together.
- Token refresh is a bounded auth recovery operation, not an infinite request retry. Test replacement/rotation and preserve a valid refresh token when the provider legitimately omits a replacement. Follow each provider's actual behavior, including uncertainty after a failed refresh response.

### Exceptions and retries

Follow Last.fm's separation of transient and permanent errors, but use provider-specific classes until a reviewed common base is justified. Do not raise `LastfmError` from Spotify/Apple. A proposed hierarchy should distinguish:

- **Transient:** connection/read failures and documented temporary service failures. Retry idempotent reads within a budget; exhaust that budget by raising, never by returning an empty batch.
- **Rate limited:** safe status and a parsed retry delay, distinguishing short rate limits from longer quota exhaustion where possible. Honor valid server delays. If a delay exceeds the job budget, fail or defer explicitly.
- **Application credentials rejected:** application configuration or access problem; no unchanged retries. This may be operationally critical.
- **User authorization expired/revoked:** attempt only documented bounded recovery, then require reconnect for that connection. Do not confuse one revoked user with failure of the entire application.
- **Forbidden or unavailable capability:** missing scope, app mode, subscription, region, or endpoint eligibility as supported by evidence; not automatically invalid credentials.
- **Bad request/account unavailable:** a permanent request or account problem; preserve a useful safe classification without copying remote prose.
- **Protocol:** malformed envelope, inconsistent paging, unexpected content type, or invalid mandatory fields. Decide whether a bounded retry is justified; never spin indefinitely on a stable schema change.
- **Page limit/coverage gap:** the batch cannot establish required coverage. Do not mark it complete or advance a clean full-window checkpoint.

Use static public messages and safe typed attributes such as HTTP status, a known error code, and bounded retry delay. Avoid raw bodies, URLs, response objects, tokens, and provider prose in exception strings. Translate transport exceptions with `raise ProviderError("Static message") from None` where they could expose request details. Never serialize Pydantic validation input; log a controlled field location/error category, not the invalid value.

Only the relevant transient exceptions enter `retry_call()`. Its current jitter mechanism is not sufficient on its own for `Retry-After` or token recovery; propose an extension or provider-local mechanism with tests. Retrying a token exchange can have different semantics from retrying a GET, so do not wrap every operation in one blind retry decorator.

### Logging and alerts

Libraries use `logging.getLogger(__name__)`; entrypoints configure logging once. Preserve stable events, for example `retry.scheduled` and `scrobble.skipped` where applicable. Aggregate malformed-row warnings once per page, with counts and a safe location.

Log operational counts, pages, attempts, status, exception type, and existing internal user/run context. Never log music names, raw response bodies, full URLs, tokens/codes/private keys, email/chat IDs, or provider account identifiers. A new `provider` extra field is not currently serialized; coordinate an allowlist change rather than assuming it appears.

Run records remain the health source. Alerts come from the job runner, not clients, exception constructors, or logging handlers. Shared error classification must eventually recognize new application-credential failures without treating ordinary user reconnect cases as a global critical outage. Add regression coverage when that shared behavior changes.

## Deliverable 4: coordinated application wiring

Keep adapters isolated until the contract and provider feasibility are accepted. A later PR sequence can then:

1. Add numbered migrations for provider connections, credential references, provenance/identity, precision, and checkpoints as the approved design requires. Preserve all synthetic existing Last.fm users/events and their deduplication behavior.
2. Add explicit source selection and consent/reconnect/disconnect actions. Define whether source changes create coverage gaps; never silently start importing pre-join history.
3. Construct the selected adapter in shared services. Keep CLI/web thin, and preserve the common job lock. Do not scatter provider switches through analytics.
4. Fetch outside the DB write transaction, enforce enrollment again in the service, then atomically save accepted observations, the safe checkpoint, and successful run status. Preserve the `before_commit`/`stage_success()` guarantee or replace it only with an equivalent reviewed design.
5. Present incomplete coverage and reconnect requirements accurately in operations. Freeze reports according to their existing rules; do not silently recalculate old reports after switching source or changing attribution.
6. Enable a provider for a consenting test user after maintainer review of the evidence, offline checks, and an isolated live smoke test. Set production scheduling according to demonstrated recovery depth.

## Required tests

Include automated tests with each adapter change. Use pytest, fake HTTP sessions/responses, injected clocks and sleep functions, synthetic fixtures, and the in-memory DB fixture for storage integration. Standard tests must run without credentials, external network access, or real retry delays.

### Client and paging

- Normal single page, true empty result, multiple pages, end of pagination, and reversed/tied observations where relevant.
- Correct auth headers, scopes/parameters, timeout settings, cursor units, exclusive/inclusive bounds, and no simultaneous incompatible cursor parameters.
- Repeated cursor/next URL, page limit, no-progress response, failure on a later page, and a history gap. Partial fetches cannot masquerade as complete success.
- Connection/read failures, retryable 5xx, retry exhaustion, non-JSON response, unexpected envelope, and response closure on every path.
- 429 with valid, missing, malformed, negative, or excessive retry delay; longer quota failure if distinguishable. Check the delay requested via a fake sleeper, not elapsed wall time.
- Unexpected redirects or next links to another origin/path cannot receive credentials. Assert no unsafe request occurs.

### Schema and event identity

- Whitespace/Unicode/case normalization, original display values retained, missing optional album/context/duration, and unexpected extra fields.
- Invalid required timestamp/identity, now-playing-like or unsupported resource entries, deleted/unavailable tracks, and nullable IDs as observed in that API.
- Repeated song at different play times yields two observations; the same observation repeated across pages stays idempotent at the persistence boundary.
- Subsecond and offset timestamps, boundary ties, multiple artist credits, album versus track artist differences, and release-date precision. Unknown duration is not zero or measured duration.
- A malformed page/required row has the documented error or incomplete-coverage outcome, with exact counts and no raw input leakage.

### Authentication

- Successful consent/exchange, denied consent, wrong/expired/replayed state, connection-owner mismatch, missing scope, and no open redirect.
- Expiry and one bounded recovery, refresh rotation/omitted replacement where applicable, revoked access, failed refresh, and no retry loop. Apple-specific token behavior follows evidence rather than Spotify assumptions.
- Credentials absent from reprs, exceptions, log output, and rendered callback errors, including provider messages that deliberately contain a fake secret or full URL.
- Disconnect stops future collection; the agreed deletion and token-cleanup behavior is tested when its persistence layer is implemented.

### Service/storage integration, when wiring is in scope

- Successful sync saves plays and advances the provider checkpoint.
- Repeated sync inserts no duplicates; separate plays of one song remain separate.
- First-page and later-page fetch failures change neither events nor checkpoint.
- Forced DB write, checkpoint write, success-staging, or commit failure rolls back the transaction and leaves an accurate failed/uncertain outcome.
- Pre-enrollment data never persists, including unexpected provider returns. Empty fully covered success can advance progress; incomplete coverage follows the explicit gap policy.
- Two provider accounts are isolated; an unselected provider is not polled; no automatic fallback or cross-provider merge happens.
- Upgrading an existing synthetic Last.fm database preserves rows, keys, checkpoints, and run outcomes. Existing operational tests continue to pass.
- Authenticated web actions and scoped callbacks enforce the agreed owner/CSRF/state boundaries when those routes are introduced.

Assertions should verify observable outcomes, not private function structure. Test failures and negative guarantees deliberately; a happy-path fixture alone is not sufficient.

## PR sequence and completion criteria

See [CONTRIBUTING](../CONTRIBUTING.md) for branch setup, required checks, and the PR description template. Suggested reviewable sequence:

1. **Research:** both provider spike notes, capability/permission recommendations, and synthetic examples. No application wiring.
2. **Contract:** small shared-boundary and storage proposal based on evidence, including unresolved choices and Last.fm compatibility. This can be documentation before code.
3. **Spotify adapter:** viable auth/client/schema/errors with offline tests; keep it unselected by the application. Split auth and history into separate PRs if needed.
4. **Apple adapter:** only capabilities demonstrated by its spike, with equivalent tests. A documented blocker is a valid alternative outcome.
5. **Shared wiring:** migrations and service/error/config/auth integration in coordinated PRs, with rollback, identity, and Last.fm regression tests.
6. **Acceptance:** consenting isolated live checks, coverage limitations, reconnect/disconnect behavior, rollout recommendation, and operating instructions. Never embed credentials or private captures in the evidence.

Each code PR must explain the changed behavior, design, validation, limitations, and compatibility/rollout implications. Require maintainer review before merging. Run `uv run ruff check .`, `uv run mypy wrapped`, and `uv run pytest -q`, plus focused adapter tests during development. Resolve failing checks and remove credential dependencies from the normal test suite.

An adapter is ready for integration when its capabilities and permitted uses are documented, behavior is tested offline, and failure, coverage, authentication, and persistence contracts are defined. Production readiness additionally requires application wiring and live acceptance checks.
