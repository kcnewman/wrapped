# Last.fm spike: findings

Spike date: 2026-10-16
Endpoint: `user.getRecentTracks`
Script: `scripts/lastfm-spike.py` (every case saves a record with status, content type, elapsed time, params without the API key, and the body)
Fixtures: `scripts/fixtures/<case>[_<tag>].json`

Status: the response shapes and error behaviour are captured. The items under "Open questions" are not done yet.

## 1. What was tested

Each case changes one thing from a working request (`limit=5` unless stated).

| Case | Change |
| --- | --- |
| `ok` | none |
| `limit_1` | `limit=1`, run once with nothing playing and once with a track playing |
| `limit_0`, `limit_1001` | limit outside the allowed range |
| `unknown_user` | `user=nobody_xyz_123456` |
| `missing_user` | `user` omitted |
| `bad_key` | `api_key=invalid` |
| `missing_key` | `api_key` omitted |
| `bad_method` | `method=user.nope` |
| `page_past_end` | `page=99999` |
| `empty_window` | `from` and `to` both in the future, run idle and while playing |
| `from_after_to` | `from` later than `to` |

## 2. Error responses

Every error returned a 4xx status with a JSON body of the form `{"message": "...", "error": <code>}` and content type `application/json`. No error arrived with HTTP 200.

| Case | HTTP | Code | Message |
| --- | --- | --- | --- |
| `limit_0`, `limit_1001` | 400 | 6 | limit param out of bounds (1-1000) |
| `missing_key` | 400 | 6 | Invalid parameters - Your request is missing a required parameter |
| `bad_method` | 400 | 3 | Invalid Method - No method with that name in this package |
| `bad_key` | 403 | 10 | Invalid API key - You must be granted a valid key by last.fm |
| `unknown_user` | 404 | 6 | User not found |
| `missing_user` | 404 | 6 | User not found |

Notes:

- Code 6 covers several different problems, and the HTTP status separates them: 400 means a bad request from our side, 404 means the user was not found.
- Omitting `user` reports "User not found" rather than a missing-parameter error.
- Observed latency across all cases: about 0.5 to 1.6 seconds.

## 3. Success responses

All success cases returned HTTP 200.

### Shape of `recenttracks.track`

The same field has several shapes, so it must be normalized before iterating.

| Situation | `track` is |
| --- | --- |
| Normal page, nothing playing | a list |
| `limit=1`, nothing playing | a list with one item |
| `limit=1`, a track playing | a list with two items: the now-playing track first, then the newest scrobble |
| Window with no scrobbles, nothing playing | an empty list |
| Window with no scrobbles, a track playing | a bare object (the now-playing track) |
| `page=99999`, a track playing | a bare object (the now-playing track) |
| `from` later than `to`, a track playing | a bare object (the now-playing track) |

### Now-playing entry

- It carries `@attr.nowplaying == "true"` and has no `date`.
- It is added to the response even when the `from`/`to` window or the page number would exclude it, and it does not count towards `total`.
- Page 1 can therefore hold `limit + 1` entries, so the item count must never be compared with `perPage`.

### `@attr` (all values are strings)

| Field | Observed behaviour |
| --- | --- |
| `page` | echoes the requested page, even past the end |
| `perPage` | echoes the requested limit |
| `totalPages` | `"0"` for an empty window; `"29"` for 145 scrobbles at 5 per page |
| `total` | scrobbles in the window; excludes the now-playing track; went from 145 to 146 when a playing track finished |
| `user` | the username |

### Limits and windows

- `limit` must be between 1 and 1000 inclusive (this corrects an earlier assumption that 200 was the maximum).
- A page past the end is not an error: it returns 200 with `page` echoing the request.
- `from` later than `to` is accepted silently and returns an empty-looking result. A swapped window in our own code would look exactly like "no new scrobbles".

### Track fields

| Field | Notes |
| --- | --- |
| `name` | track title (string) |
| `artist` | object `{"mbid", "#text"}`; the name is under `#text` |
| `album` | object `{"mbid", "#text"}`; can be empty |
| `mbid` | track MBID; empty string when unknown |
| `date.uts` | Unix seconds as a string; Last.fm documents the scrobble time as when playback started (verify) |
| `date.#text` | display text only |
| `image`, `streamable`, `url` | not used |

### Identity quality in the sample (one page of 50)

- The artist MBID was present on roughly a third of the rows. Local gospel artists had none.
- One artist appeared in three forms: `JAŸ-Z` with an MBID, `JAŸ-Z` without one, and `Jaÿ-Z` without one. Name-based keys are the primary identity; MBIDs are only an attribute.

## 4. Manual tests

| Test | Result | Confidence |
| --- | --- | --- |
| Pause then resume | One scrobble on the Last.fm profile page, not two | Seen on the page; not yet checked through the endpoint |
| Spotify offline mode, then reconnect | The plays did not appear | Observed; consistent with forum reports that Spotify's mobile app does not submit offline plays |
| Same track twice in a row | Two online plays are recorded separately (a track repeated 7 times appears with gaps of 2 to 8 minutes) | Seen in the saved page. The two plays that did not record in the manual test were probably the offline ones; unconfirmed |

## 5. Design consequences

### `_get`

- Send the request, then read and parse the body before looking at the status. The useful error text is in the JSON of the 4xx response, so do not call `raise_for_status()` first.
- Keep a guard for a 200 response containing an `error` key, even though it was not observed.
- Map status and code to exception types:

| Condition | Exception | Retry |
| --- | --- | --- |
| 400 with code 3 or 6 | bad request (our bug) | no |
| 403 with code 10 (or 26) | credential problem | no, alert the owner |
| 404 with code 6 | user not found | no, mark the user failed |
| 429, 5xx, timeouts, connection errors | transient | yes, backoff with jitter |
| Last.fm codes 8, 11, 16, 29 | transient | yes (confirm against the current Last.fm error list; no real example seen yet) |
| Body is not JSON | transport error | yes, limited |

- Never put the request URL in an exception message: the API key is in the query string.

### `iter_recent`

- Reject `from > to` before sending anything.
- Pin `to` for the whole run so new scrobbles cannot shift the pages.
- Normalize `track` (list, bare object, empty list, missing) to a list on every page.
- Drop every entry with `@attr.nowplaying == "true"`, on every page.
- Read `totalPages` from `@attr`, converting it to an int. Stop when `page >= totalPages`; `totalPages == 0` stops after the first request.
- Enforce a maximum page count per run.
- Let errors propagate after `_get` has used its retries.

### Mapper

- Convert numeric strings to ints.
- Convert empty strings to `None`.
- Read names from `#text`.
- Build the dedup key from `(user, uts, artist_key, track_key)` and never from an MBID.

### Tests (one per fixture)

- `bad_key` raises the credential error.
- `unknown_user` raises user-not-found.
- `limit_0` and `bad_method` raise the bad-request error.
- `ok` yields the expected events.
- `limit_1` playing and idle both yield the right events.
- `empty_window` idle and playing both yield nothing.
- `page_past_end` stops cleanly.
- `from_after_to` is rejected before any request.

## 6. Open questions

- [ ] Are `from` and `to` inclusive? Query one scrobble's `uts` as `from=T&to=T`, then `from=T+1`.
- [ ] Does the now-playing entry also appear on page 2 and later of a real multi-page run?
- [ ] Synthetic fixtures for rate limit (29), service offline (11), a 5xx, an HTML error page and a timeout, clearly marked as synthetic.
- [ ] What does a hidden profile return? (Not documented anywhere I found.)
- [ ] Does pause and resume also produce a single entry through the endpoint?
- [ ] Repeat of one track, played online twice in a row: confirm it is recorded twice.
- [ ] Read the Last.fm API terms: non-commercial use, any retained-data cap, rate limits, attribution, and any restriction on AI use of the data.

## 7. Known limits of this data source

- Offline plays on Spotify mobile are not scrobbled, so a friend who listens offline will have those plays missing.
- Apple Music has no native Last.fm support; friends need a third-party scrobbler and an onboarding test.
- There is no track duration, so minutes listened cannot be computed.
- Late scrobbles from some clients arrive with old timestamps, so sync should re-read a window of about 14 days (confirm the limit in the Last.fm docs).

## 8. Fixture hygiene

The saved fixtures include the username and listening history. Keep them out of a public repository, or trim them (fewer tracks, no image URLs) before committing.
