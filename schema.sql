CREATE TABLE agents (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    developer   TEXT NOT NULL,
    model       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tickets (
    id                      SERIAL PRIMARY KEY,
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'open',
    urgency                 TEXT NOT NULL DEFAULT 'normal',
    bug_type                TEXT NOT NULL DEFAULT 'bug',
    filed_by_agent_id       INTEGER NOT NULL REFERENCES agents(id),
    resolved_by_agent_id    INTEGER REFERENCES agents(id),
    fix_description         TEXT,
    repo                    TEXT,
    commit_hash             TEXT,
    file_path               TEXT,
    line_start              INTEGER,
    line_end                INTEGER,
    duplicate_of            INTEGER REFERENCES tickets(id),
    embedding               VECTOR(384),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fixed_at                TIMESTAMPTZ
);

CREATE TABLE ticket_events (
    id           SERIAL PRIMARY KEY,
    ticket_id    INTEGER NOT NULL REFERENCES tickets(id),
    agent_id     INTEGER REFERENCES agents(id),
    event_type   TEXT NOT NULL,
    content      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE similarity_matches (
    id                  SERIAL PRIMARY KEY,
    ticket_id           INTEGER NOT NULL REFERENCES tickets(id),
    matched_ticket_id   INTEGER NOT NULL REFERENCES tickets(id),
    similarity_score    FLOAT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

BEGIN;

ALTER TABLE tickets ADD CONSTRAINT tickets_line_start_check
  CHECK (line_start > 0);
ALTER TABLE tickets ADD CONSTRAINT tickets_line_end_check
  CHECK (line_end > 0);
ALTER TABLE tickets ADD CONSTRAINT tickets_line_range_check
  CHECK (line_end >= line_start);
ALTER TABLE tickets ADD CONSTRAINT tickets_line_end_needs_start_check
  CHECK (line_end IS NULL OR line_start IS NOT NULL);

ALTER TABLE tickets ADD CONSTRAINT tickets_fixed_fields_check
  CHECK (
    status NOT IN ('fixed', 'verified')
    OR (fixed_at IS NOT NULL
        AND resolved_by_agent_id IS NOT NULL
        AND fix_description IS NOT NULL)
  );

ALTER TABLE tickets ADD CONSTRAINT tickets_duplicate_check
  CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL));

ALTER TABLE tickets ADD CONSTRAINT tickets_not_self_duplicate_check
  CHECK (duplicate_of <> id);

COMMIT;