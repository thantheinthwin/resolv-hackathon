-- Adopt existing unversioned case databases and the listing storage from PR #17.
CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY, body TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS listing_photos (
    path TEXT PRIMARY KEY,
    mime TEXT NOT NULL,
    image BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_links (
    case_id TEXT PRIMARY KEY,
    digest BLOB UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS replaced_uploads (case_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS initialized (name TEXT PRIMARY KEY);
