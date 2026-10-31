CREATE TABLE IF NOT EXISTS papers (
    id            TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    content_hash  TEXT NOT NULL UNIQUE,
    title         TEXT,
    index_status  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    paper_id     TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_number  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    words        TEXT NOT NULL,
    PRIMARY KEY (paper_id, page_number)
);

CREATE TABLE IF NOT EXISTS http_cache (
    url        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    body       TEXT,
    fetched_at REAL NOT NULL,
    -- Composite: the same URL can be fetched as json and as text, and a
    -- single-column key would make the two evict each other on every call.
    PRIMARY KEY (url, kind)
);
