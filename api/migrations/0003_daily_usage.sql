CREATE TABLE usage (
    day TEXT PRIMARY KEY,
    total INTEGER NOT NULL CHECK (total >= 0),
    salt BLOB NOT NULL
);
CREATE TABLE daily_ip_usage (
    day TEXT NOT NULL REFERENCES usage(day) ON DELETE CASCADE,
    peer_digest BLOB NOT NULL,
    total INTEGER NOT NULL CHECK (total >= 0),
    PRIMARY KEY (day, peer_digest)
);
