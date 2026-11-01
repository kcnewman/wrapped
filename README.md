# Wrapped

Self-hosted listening analytics and monthly reports.

Wrapped collects listening history from enrollment onward and turns it into monthly reports with rankings, listening patterns, and fact-based narration. Reports are delivered through Telegram or email. An administrator manages enrollment, collection, and delivery through a web dashboard. Annual reports reuse the same analytics engine.

**Status: under development.** Last.fm enrollment and incremental collection are implemented. Analytics are in progress. Report generation, report delivery, AI narration, and dashboard management are incomplete.

## Planned features

- Monthly and annual reports covering top artists, tracks, albums, discoveries, listening patterns, streaks, and period comparisons.
- AI narration constrained to computed facts, with grounding validation and deterministic fallback text.
- Telegram and email delivery with duplicate-send protection.
- Administrator dashboard for user management, sync monitoring, data inspection, report previews, and delivery controls.
- Scheduled collection, durable run records, failure alerts, backups, and restore procedures.
- Future visual and video formats generated from the same report facts.

This is an independent project, not an official Spotify or Apple product. Direct integrations with those services are research and future development work, subject to data capabilities, access, and permitted use. Last.fm is the only implemented listening source today.

## Collection and report rules

Collection starts when a person joins. Wrapped never imports pre-enrollment plays, even when a source returns them. Catching up on missed plays recorded after enrollment is allowed.

Reports use local calendar periods and require at least **15 elapsed days of enrollment within the period**. Collection starts immediately; eligibility only controls reporting. Eligible first periods are labelled partial. An ineligible period produces no report or delivery. A quiet eligible period receives a short deterministic message rather than an AI-generated story.

Names are normalized for comparison while their original spelling remains available for display. Re-fetching the same observation does not create another play. Playing the same song again at a different timestamp does.

Wrapped distinguishes recorded plays, calculated facts, estimates, and missing data. A song's catalog length is not measured listening time. Global fan percentiles, listening age, mood, or audio characteristics are not inferred from data that cannot support them. See the [product decisions and metric definitions](docs/product-decisions.md).

## Architecture

```text
Selected listening source
        ↓
Provider client → response validation and mapping
        ↓
Enrollment-bounded sync → SQLite events and checkpoint
        ↓
Deterministic metrics → selected facts → validated narration
        ↓
Report rendering → Telegram / email / future visual formats

Admin dashboard and scheduler → shared service actions
Run records / JSON logs / failure alerts → operational visibility
```

The current implementation uses Python 3.12+, requests, Pydantic, SQLite, FastAPI, and Jinja2. The deployment plan uses a single web worker and serialized writer jobs on a persistent volume. The CLI serves scheduling and troubleshooting; the web dashboard is the intended daily admin interface.

## Roadmap

Current milestone: **P4 — analytics**. Automated acceptance coverage remains incomplete.

- **P0–P1: foundations and Last.fm research.** Packaging, development checks, CI configuration, captured-response research; some research questions remain open.
- **P2–P3: client, mapping, storage, and sync.** Functional Last.fm ingestion, normalization, enrollment boundaries, duplicate protection, migrations, and transactional run outcomes. Dedicated ingestion regression coverage remains outstanding.
- **P4: analytics — current feature work.** Periods, eligibility, counts and rankings are underway; complete metrics, report assembly, and preview remain.
- **P5–P6: delivery and narration.** Actual report delivery, duplicate-send protection, structured narration, validation, and evaluation. Owner failure alerts already exist.
- **P7: complete the dashboard.** Authentication, runs, logs, and basic health exist; user management, report previews, sync actions, and Telegram linking remain.
- **P8–P10: deployment, email, onboarding, and release preparation.** Scheduling, backups, restore verification, email, onboarding, and a synthetic demo. Container files are currently placeholders.
- **Future extensions:** video presentation and viable, permitted Spotify and Apple Music adapters. Provider research can proceed in parallel; production enablement is a separate integration milestone.

## Documentation

- [Development and operations](docs/development.md): local setup, enrollment and sync commands, logging, run records, and verification.
- [Contributor guide](CONTRIBUTING.md): branches, PRs, review expectations, and checks.
- [Spotify and Apple Music integration handoff](docs/provider-integration-handoff.md): assignment, architecture, authentication, errors, coverage, tests, and delivery sequence.
- [Product decisions](docs/product-decisions.md): accepted definitions, proposals, limitations, and unresolved choices.
- [Last.fm spike notes](docs/lastfm-spike.md): existing provider observations and open research questions.
