CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    lastfm_user TEXT UNIQUE,
    tz TEXT,
    channel TEXT CHECK (channel IN ('email', 'telegram')),
    address TEXT,
    history_from INTEGER,
    last_sync INTEGER,
    paused INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    user_id INTEGER,
    uts INTEGER,
    artist TEXT,
    artist_key TEXT,
    track TEXT,
    track_key TEXT,
    album TEXT,
    album_key TEXT,
    artist_mbid TEXT,
    PRIMARY KEY (user_id, uts, artist_key, track_key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS reports (
    user_id INTEGER,
    period TEXT,
    stats_json TEXT,
    narration_json TEXT,
    prompt_version TEXT,
    model TEXT,
    created_at INTEGER,
    PRIMARY KEY (user_id, period)
);

CREATE TABLE IF NOT EXISTS deliveries (
    user_id INTEGER,
    period TEXT,
    sent_at INTEGER,
    PRIMARY KEY (user_id, period)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    kind TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    pages INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error TEXT
);
