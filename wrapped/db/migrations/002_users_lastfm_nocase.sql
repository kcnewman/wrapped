CREATE UNIQUE INDEX users_lastfm_user_nocase
ON users (lastfm_user COLLATE NOCASE);
