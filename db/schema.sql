CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash     TEXT    UNIQUE NOT NULL,
    url          TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    company      TEXT,
    location     TEXT,
    salary_min   INTEGER,            -- MXN brutos/mes
    salary_max   INTEGER,
    salary_raw   TEXT,               -- string original antes de parsear
    description  TEXT,
    tags         TEXT,               -- JSON array: ["Python","AWS","Docker"]
    source       TEXT    NOT NULL,   -- 'occ'|'computrabajo'|'techjobsmx'|'getonbrd'
    remote       INTEGER DEFAULT 0,  -- 0/1
    score        REAL    DEFAULT 0.0,
    notified     INTEGER DEFAULT 0,  -- 0/1 enviado a Telegram
    scraped_at   TEXT    NOT NULL,   -- ISO 8601
    posted_at    TEXT,               -- si la fuente lo provee
    applied      INTEGER DEFAULT 0,  -- 0/1 marcado como aplicado
    applied_at   TEXT,               -- timestamp cuando se aplico
    application_notes TEXT,          -- notas del usuario sobre la aplicacion
    reminded     INTEGER DEFAULT 0   -- 0/1 re-notificado una vez
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    jobs_found   INTEGER DEFAULT 0,
    jobs_new     INTEGER DEFAULT 0,
    status       TEXT    DEFAULT 'running',  -- 'running'|'success'|'error'
    error_msg    TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_source     ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_notified   ON jobs(notified);
CREATE INDEX IF NOT EXISTS idx_jobs_score      ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC);

-- Manual job decisions (override scoring)
CREATE TABLE IF NOT EXISTS job_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash     TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    company      TEXT,
    source       TEXT    NOT NULL,
    decision     TEXT    NOT NULL,  -- 'interested' | 'skipped'
    profile_name TEXT,              -- which user made the decision
    score_at_time REAL   DEFAULT 0.0,
    notes        TEXT,
    decided_at   TEXT    NOT NULL   -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_decisions_url_hash ON job_decisions(url_hash);
CREATE INDEX IF NOT EXISTS idx_decisions_profile  ON job_decisions(profile_name);
