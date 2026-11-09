-- Schéma PostgreSQL simple (idempotent). Usage : psql $DB -f schema.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        VARCHAR(20) NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT,
    raw_text        TEXT,
    published_at    TIMESTAMPTZ,
    screenshot_path TEXT,
    raw_metadata    JSONB,
    reliability     VARCHAR(20) NOT NULL DEFAULT 'unknown',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sources_platform ON sources (platform);
CREATE INDEX IF NOT EXISTS ix_sources_url      ON sources (url);

CREATE TABLE IF NOT EXISTS events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id           UUID NOT NULL REFERENCES sources(id),
    event_type          VARCHAR(50) NOT NULL,
    occurred_on         DATE NOT NULL,
    city                VARCHAR(255) NOT NULL,
    location_raw        TEXT,
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    description         TEXT NOT NULL,
    actors              JSONB NOT NULL DEFAULT '[]',
    victims             JSONB NOT NULL DEFAULT '[]',
    injury_level        VARCHAR(20) NOT NULL DEFAULT 'unknown',
    legal_status        VARCHAR(20) NOT NULL DEFAULT 'unknown',
    verification_status VARCHAR(20) NOT NULL,
    confidence          SMALLINT NOT NULL CHECK (confidence BETWEEN 0 AND 5),
    source_urls         JSONB NOT NULL DEFAULT '[]',
    needs_review        BOOLEAN NOT NULL DEFAULT TRUE,
    extracted_keywords  JSONB NOT NULL DEFAULT '[]',
    status              VARCHAR(30) NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_events_event_type  ON events (event_type);
CREATE INDEX IF NOT EXISTS ix_events_city        ON events (city);
CREATE INDEX IF NOT EXISTS ix_events_occurred_on ON events (occurred_on);
CREATE INDEX IF NOT EXISTS ix_events_status      ON events (status);

CREATE TABLE IF NOT EXISTS event_sources (
    event_id  UUID NOT NULL REFERENCES events(id)  ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, source_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type  VARCHAR(50) NOT NULL,
    status     VARCHAR(30) NOT NULL DEFAULT 'pending',
    payload    JSONB NOT NULL DEFAULT '{}',
    result     JSONB,
    error      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_tasks_status    ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_task_type ON tasks (task_type);
