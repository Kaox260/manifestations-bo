-- Schéma PostgreSQL simple (idempotent). Usage : psql $DB -f schema.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sources (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(255) NOT NULL,
    source_type  VARCHAR(50)  NOT NULL,
    url          TEXT,
    raw_metadata JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sources_source_type ON sources (source_type);

CREATE TABLE IF NOT EXISTS events (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id             UUID REFERENCES sources(id) ON DELETE SET NULL,
    title                 VARCHAR(500) NOT NULL,
    description           TEXT,
    event_type            VARCHAR(50) NOT NULL,
    city                  VARCHAR(255),
    department            VARCHAR(100),
    region                VARCHAR(100),
    latitude              DOUBLE PRECISION,
    longitude             DOUBLE PRECISION,
    occurred_on           DATE,
    status                VARCHAR(30) NOT NULL DEFAULT 'pending',
    participants_estimate INTEGER,
    confidence            DOUBLE PRECISION,
    raw_metadata          JSONB NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_events_event_type  ON events (event_type);
CREATE INDEX IF NOT EXISTS ix_events_city        ON events (city);
CREATE INDEX IF NOT EXISTS ix_events_occurred_on ON events (occurred_on);
CREATE INDEX IF NOT EXISTS ix_events_status      ON events (status);

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
