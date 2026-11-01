# Wrapped: product decisions and metric definitions

Recorded: 2026-11-01

Defines product behavior, metric calculations, integration constraints, and open design questions. Accepted decisions describe requirements; implementation status is tracked in the [roadmap](../README.md#roadmap).

Record changes as dated amendments and update affected documentation. Preserve the definitions used by previously generated reports.

## Status vocabulary

- **Accepted:** agreed product behavior or engineering direction. Implementation may still be pending.
- **Proposed:** a candidate, not an approved calculation or implementation commitment.
- **Deferred:** deliberately outside the current implementation step.
- **Open:** evidence or a product choice is still needed.
- **Rejected:** do not implement unless a later decision explicitly supersedes it.

## 1. Product direction

### D01 — Fact-based listening reports

Status: **Accepted**

Spotify's year-end Wrapped is the experience benchmark: accurate facts, meaningful personal stories, attractive reveals, and shareable results. The goal is an independently designed product, not a claim to reproduce Spotify's private data or algorithms.

Reports provide monthly updates, continuity across periods, transparent definitions, and insights supported by retained listening history.

Separate three layers:

1. Deterministic calculations produce facts.
2. Story selection chooses noteworthy, supported facts.
3. Narration and renderers present those facts through messages, the dashboard, cards, and eventually video.

Multiple renderers consume the same verified facts. Unsupported measurements must not appear in report content.

### D02 — The admin interface is the web dashboard

Status: **Accepted**

The final daily interface is the owner-authenticated dashboard. The CLI remains a thin adapter for scheduling and occasional troubleshooting. Both call shared service actions; neither should duplicate enrollment, sync, or report-generation workflows.

## 2. Collection and reporting rules

### D03 — Collection begins at enrollment

Status: **Accepted**

- The application assigns `history_from` from the server clock at enrollment.
- It is an immutable lower bound for stored plays, not a user-selectable historical start date.
- Never import pre-enrollment listening, including unexpected provider responses.
- Recovering missed **post-enrollment** plays after an outage is allowed; that is not historical backfill.
- A future export importer must also discard pre-enrollment observations.
- Collection starts immediately. Report eligibility must never delay sync.

### D04 — Reports require 15 elapsed days within their period

Status: **Accepted**

Report months are local calendar months converted to UTC Unix boundaries. Membership uses `[start, end)`: include the start, exclude the end.

For completed periods:

```text
tracked_start = max(period_start, history_from)
observed_seconds = max(0, period_end - tracked_start)
eligible = observed_seconds >= 15 * 24 * 60 * 60
```

For in-progress previews, use `min(period_end, now)` as the observation end. Do not credit future time. A later retry must not make an ineligible past period eligible.

This measures elapsed enrollment coverage, not days with listening activity. Eligible first periods containing enrollment are labelled partial and use only post-enrollment events. Minimum-duration eligibility does not itself mean the period is complete; final monthly report generation also requires that the period has ended.

Ineligible periods create no report, narration, or delivery. An eligible period with fewer than 20 plays uses the deterministic quiet-period message rather than an LLM. Comparisons are suppressed when the previous period has fewer than 50 plays, as specified in the baseline.

### D05 — Failure records must reflect the committed outcome

Status: **Accepted**

For sync, plays, checkpoint advancement, and successful run status commit in the same application-data transaction. Enrollment similarly commits the new user and successful run association together. The initial running record is committed separately so an unsuccessful attempt remains visible.

On application-data rollback, record failure separately without claiming committed inserts or referencing a rolled-back new user. A post-commit handling error must not overwrite committed success with failure. If the outcome cannot be confirmed, report that uncertainty explicitly.

## 3. Metric definitions and honesty labels

### D06 — Distinguish observations, calculations, estimates, and gaps

Status: **Accepted**

- **Observed:** supplied by a source, with its source and meaning preserved. An observed provider entry is not automatically proof of full playback.
- **Derived:** deterministically calculated from defined inputs, such as unique tracks within a window.
- **Estimated:** relies on an assumption or inference that is disclosed alongside the result.
- **Incomplete:** required coverage or metadata is missing. Say what is missing rather than presenting a complete total.

Important definitions:

- **Recorded play:** one deduplicated listening observation accepted from the selected source. Provider qualification rules may differ.
- **Total plays:** the number of accepted events in the report window, not the number of distinct tracks.
- **Unique artists:** distinct artist identities under the documented attribution policy. Current Last.fm calculations use normalized artist credit strings; they do not resolve every collaborator into a separate artist.
- **Unique tracks:** current Last.fm grouping uses `(artist_key, track_key)`. The same title by different artists is not one track.
- **New to this tracker:** first observed in the user's retained, post-enrollment data. It does not mean first heard in their life.
- **Album plays:** recorded track plays associated with an album, not proof that the user listened to the complete album.
- **Measured listening time:** playback duration explicitly recorded by a source, not the catalog length of the song.

### D07 — Duration estimates and measurements

Status: **Accepted principle; proposed future metric**

Converting milliseconds to minutes is unit normalization. Inferring how long someone listened is estimation. Mock values are suitable for synthetic fixtures, not presentation as measured production data.

Keep these concepts separate if duration support is implemented:

- Catalog track duration.
- Recorded listened duration, when available.
- Estimated duration, when a documented method is used.
- The source, calculation version, and metadata coverage behind the displayed result.

Unknown measured duration remains unknown, not zero and not an estimate written into the measured field.

**Proposed metric: full-track-equivalent runtime**

```text
full_track_equivalent_minutes =
    sum(known catalog duration_ms for accepted plays) / 60_000
```

For example, twenty recorded plays of four-minute tracks produce eighty full-track-equivalent minutes. They do not establish eighty minutes of actual listening.

If some plays lack catalog duration, disclose how many contributed to this calculation and how many did not. Do not silently extrapolate the subtotal to all plays. This figure is not a guaranteed upper or lower bound on actual listening time.

An arbitrary multiplier such as 50% has **not** been selected. If a future estimate uses an assumed listening fraction, label it as an assumption, explain its basis, and version the formula. Documenting an assumption does not make it empirically accurate.

This remains a future extension, not a new requirement blocking current P4 counts and rankings. Retain sufficient calculation metadata for frozen reports to remain interpretable after definitions change.

### D08 — Provider play rules are not duration measurements

Status: **Accepted distinction; source behavior still requires validation**

Spotify documents a song stream as counting after at least 30 seconds. Last.fm's scrobbling guidance requires a track longer than 30 seconds and playback of half its length or four minutes, whichever is reached first. These are different definitions.

Neither rule establishes the exact listened duration of a history entry. Do not assume Spotify's public stream-counting rule also specifies the precise inclusion behavior of its recently-played endpoint. Validate that endpoint independently. A track/catalog ID identifies content, not an individual play.

Sources: [Spotify stream counting](https://support.spotify.com/us/artists/article/how-your-streams-are-counted/), [Last.fm scrobbling rules](https://www.last.fm/api/scrobbling).

### D09 — Do not invent unavailable comparisons or characteristics

Status: **Accepted**

- Global fan percentiles require population-wide comparison data or a supplied result for a stated period. A personal history response does not provide the distribution.
- A ranking within a consenting cohort must identify the cohort and its size. It must not be presented as a worldwide percentile. The comparison method and coverage requirements remain open.
- A supplied annual Spotify Wrapped fan percentage is not a freshly calculated monthly percentile.
- Spotify-style listening age requires age-group comparisons as well as release-era patterns. Personal history alone cannot reproduce it. A separately defined music-era indicator remains proposed.
- Artist genres or community tags require enrichment and matching. They do not automatically establish a track's genre.
- Mood tags describe music metadata, not a listener's mental health or actual emotional state.
- Energy and danceability need appropriate feature data or a separately defined, permitted analysis method. Do not infer authoritative scores from names or fabricate unavailable values.

Genre enrichment, era-based stories, and any additional scoring method need explicit definitions and missing-data handling before becoming report facts.

Sources: [Spotify's 2025 Wrapped methodology](https://newsroom.spotify.com/2025-12-03/how-your-wrapped-is-made/), [Spotify data-download contents](https://support.spotify.com/us/article/understanding-your-data/), [Last.fm artist tags](https://www.last.fm/api/show/artist.getTopTags).

## 4. Narration and provider permissions

### D10 — Code calculates; AI narrates selected facts

Status: **Accepted**

The application calculates metrics before narration. The narrator receives selected computed facts and necessary descriptive information, not the raw provider response, event-by-event history, credentials, or account identifiers.

Artist and track names may be included when needed for the story. Validate narration against the supplied facts; do not let the model supply missing measurements, cohort statistics, or unsupported personal conclusions. Retain deterministic fallback behavior.

This design limits disclosure and helps grounding. It is **not** a determination that provider permissions allow every derived metric or AI use.

### D11 — Provider access and permitted use

Status: **Accepted**

API access does not establish permission for every downstream use. Product definitions and terms do not override provider conditions.

Spotify's developer policy restricts derived listening/user metrics, ingestion of Spotify Content into AI models, and synchronization of sound recordings with visual media. Assess applicability and obtain necessary permissions before implementing these uses. Aggregation or a different data source does not establish an exemption.

Recheck current access rules and terms at implementation time. This record is a feasibility warning, not legal clearance or an assertion that all integrations are prohibited.

Sources: [Spotify Developer Policy, III.6 and III.13–14](https://developer.spotify.com/policy), [Spotify API access changes](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api).

## 5. Future provider architecture and evidence

### D12 — Shared domain events, separate provider adapters

Status: **Accepted direction; implementation deferred**

Keep provider authentication, HTTP behavior, pagination, and response mapping inside provider-specific adapters. Analytics should consume normalized domain events rather than import Spotify, Apple, or Last.fm clients.

Do not introduce a large provider framework now. When a second provider is technically viable and permitted, define a small shared contract using its demonstrated requirements. That contract must communicate coverage and checkpoint semantics, not merely expose identically named methods.

Start with an explicitly selected primary source per user. Automatic failover and simultaneous multi-source ingestion are **deferred**, pending a cross-source identity and deduplication policy. Last.fm's current event key does not prove that a Spotify observation and a Last.fm observation are the same play.

Future provider connections will need their own account references, credentials, checkpoints, precision, and capability metadata. Exact storage design is open. Preserve provider-native identifiers and timestamp precision where needed; never confuse a track ID with an event ID.

### D13 — Spotify fixture observations are evidence, not completeness guarantees

Status: **Observed sample; future integration deferred and conditional**

A ten-entry recently-played sample reviewed on 2026-11-01 contained:

- Ten recently-played entries and a next-page link.
- Catalog duration and album release-date metadata on all ten entries.
- Multiple credited artists on eight entries.
- Missing playback context on seven entries.
- No genre or popularity fields in the supplied track data.

These counts describe that sample only. They are not provider-wide guarantees.

Consequences for a future adapter:

- Keep one event per play. Choose primary-artist, full-credit, or fractional attribution explicitly; do not duplicate listening events for collaborators.
- Treat absent context as unknown, not automatically library playback or direct selection.
- Respect release-date precision. An album edition's release year is not automatically the original recording's release year.
- Pagination recovers only what the endpoint exposes. Verify recovery limits and mark gaps rather than promising complete monthly totals from one successful request.
- Track duration does not reveal elapsed listening, skips, or completion.

Spotify's artist genre field and Audio Features endpoint are currently documented as deprecated; access to audio features is restricted for new use cases. Do not promise genre, energy, or danceability coverage merely because documentation or an older example contains those fields.

Sources: [Recently played](https://developer.spotify.com/documentation/web-api/reference/get-recently-played), [Artist metadata](https://developer.spotify.com/documentation/web-api/reference/get-an-artist), [Audio features](https://developer.spotify.com/documentation/web-api/reference/get-audio-features), [Access restrictions](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api).

### D14 — Personal data exports are a distinct possible source

Status: **Proposed; no importer authorized or implemented by this decision**

Spotify documents an Extended Streaming History download with recorded playback milliseconds and playback-ending information. A separate Wrapped-data package may contain already-computed annual statistics, including some fan percentages where available.

These exports are not equivalent to the Web API history response and are not a live API replacement. Any future importer must respect enrollment boundaries, deduplicate observations, validate timestamp meanings, and discard unnecessary private fields such as IP addresses. Permissions, consent, and deletion requirements still need review.

Source: [Spotify data-download contents](https://support.spotify.com/us/article/understanding-your-data/).

### D15 — Apple Music is a future research target

Status: **Deferred; capability and permission review required**

Apple documents recently-played tracks at `GET /v1/me/recent/played/tracks` and a separate recently-played resources endpoint. Their existence is not evidence that they provide a complete, timestamped ledger of individual listening events.

Before promising an Apple adapter, capture evidence for:

- Individual timestamps, their meaning and precision, and repeated-play behavior.
- Pagination, retention, synchronization delays, and outage recovery.
- Catalog duration versus measured listening duration.
- Authentication, user consent, and account requirements.
- Storage, deletion, attribution, and other usage restrictions.

Do not assume MusicKit's device-specific last-played metadata is equivalent to cross-device event history. No integration implementation is part of current P4 work.

Sources: [Apple recently-played tracks](https://developer.apple.com/documentation/applemusicapi/get-v1-me-recent-played-tracks), [Recently-played resources](https://developer.apple.com/documentation/applemusicapi/get-recently-played-resources), [MusicKit lastPlayedDate](https://developer.apple.com/documentation/musickit/song/lastplayeddate).

## 6. Roadmap and working sequence

Status: **Accepted**

The P0–P10 sequence covers foundations, Last.fm research, client/mapping, storage/sync, analytics, delivery, narration, the admin dashboard, deployment, email/onboarding, and release preparation.

Current core development is P4: period boundaries, eligibility, deterministic statistics, and report facts. Provider research and isolated adapters can proceed in parallel; application wiring and production enablement require separate review.

Video generation is a future extension after P0–P10. Spotify and Apple Music production integration depends on capability assessments, usage permissions, tested adapters, and reviewed application changes. These extensions are outside the current analytics milestone.

Core regression test authoring is currently deferred until after deployment. Manual checks and isolated diagnostics support development but do not satisfy automated acceptance requirements. Existing automated tests remain applicable; new provider work requires offline automated coverage.

Overdue-sync monitoring is scheduled for dashboard and deployment work.

## 7. Privacy and outstanding choices

Raw captures and data exports are private working data, not demo assets. Use reviewed synthetic or sanitized examples for version control. Do not include raw listening history, credentials, private account details, or full API request URLs in logs or this decision record.

Store private captures under the ignored `/scripts/fixtures/` directory. Verify ignore coverage before staging files; captures stored elsewhere require an explicit ignore rule or relocation.

Open decisions:

1. Whether to adopt full-track-equivalent runtime, a separately justified listening-time estimate, or neither; define labels, precision, method version, and metadata coverage first.
2. Artist-credit attribution and cross-provider identity/deduplication rules.
3. A reliable, permitted enrichment source for genres, release-era information, or audio characteristics.
4. Which features can proceed after each provider's capability and permission review.
5. Video format, delivery, asset rights, and narration style.
6. Any local-cohort comparison method, consent, eligibility, and minimum sample requirements.

For each resolution, record the date, status, rationale, supporting evidence, and affected milestone.

## Amendment — 2026-11-01: parallel provider development

Status: **Accepted**

Spotify and Apple Music research and isolated adapter development may proceed alongside the core Last.fm implementation. This supersedes earlier deferral of provider development in D12 and D15. Production enablement still requires validated capabilities, permitted use, integration testing, and reviewed application wiring.

Provider contributions include capability assessments, an adapter contract, isolated implementations, and offline tests delivered through reviewed PRs. Shared models, migrations, authentication routes, source selection, and production wiring require coordinated review. Enrollment boundaries, one primary source per user, explicit coverage, and transactional run outcomes remain required.

Provider changes require automated tests independently of the deferred core regression coverage.

See the [provider handoff](provider-integration-handoff.md), [contributor guide](../CONTRIBUTING.md), and [development guide](development.md).
