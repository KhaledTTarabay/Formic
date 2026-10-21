BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

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
    claimed_at              TIMESTAMPTZ,
    claimed_by_agent_id     INTEGER REFERENCES agents(id),
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
    fixed_at                TIMESTAMPTZ,
    verified_by_agent_id     INTEGER REFERENCES agents(id),
    verified_at              TIMESTAMPTZ
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
    outcome             TEXT NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


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
    status NOT IN ('fixed', 'wont_fix', 'cannot_reproduce', 'verified')
    OR (fixed_at IS NOT NULL
        AND resolved_by_agent_id IS NOT NULL
        AND fix_description IS NOT NULL)
  );

ALTER TABLE tickets ADD CONSTRAINT tickets_duplicate_check
  CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL));

ALTER TABLE tickets ADD CONSTRAINT tickets_not_self_duplicate_check
  CHECK (duplicate_of <> id);

ALTER TABLE tickets ADD CONSTRAINT ticket_status_check
  CHECK (status IN ('open', 'in_progress', 'fixed', 'wont_fix', 'cannot_reproduce', 'duplicate', 'verified'));

ALTER TABLE tickets ADD CONSTRAINT ticket_urgency_check
  CHECK (urgency in ('low', 'normal', 'high', 'critical'));

ALTER  TABLE tickets ADD CONSTRAINT ticket_bug_check
  CHECK (bug_type in ('bug','crash', 'regression','test_failure', 'build_failure', 'performance', 'security'));

ALTER TABLE tickets ADD CONSTRAINT tickets_title_not_blank_check
  CHECK (length(trim(title)) > 0);

ALTER TABLE tickets ADD CONSTRAINT tickets_description_not_blank_check
  CHECK (length(trim(description)) > 0);

ALTER TABLE tickets ADD CONSTRAINT tickets_in_progress_claimed_check
  CHECK (status <> 'in_progress'
    OR (claimed_by_agent_id IS NOT NULL AND claimed_at IS NOT NULL));

ALTER TABLE tickets ADD CONSTRAINT tickets_verified_fields_check
  CHECK (status <> 'verified'
    OR (verified_by_agent_id IS NOT NULL AND verified_at IS NOT NULL));

ALTER TABLE tickets ADD CONSTRAINT tickets_verifier_not_resolver_check
  CHECK (verified_by_agent_id IS NULL OR verified_by_agent_id <> resolved_by_agent_id);

ALTER TABLE tickets ADD CONSTRAINT tickets_fix_description_not_blank_check
  CHECK (fix_description IS NULL OR length(trim(fix_description)) > 0);


ALTER TABLE ticket_events ADD CONSTRAINT ticket_events_type_check
  CHECK (event_type IN ('filed', 'claimed', 'unclaimed', 'resolved', 'status_changed', 'comment', 'verified', 'reopened', 'marked_duplicate'));


ALTER TABLE similarity_matches ADD CONSTRAINT similarity_matches_outcomes_check
  CHECK (outcome IN ('pending', 'confirmed', 'rejected'));

ALTER TABLE similarity_matches ADD CONSTRAINT similarity_matches_unique_pair
  UNIQUE (ticket_id, matched_ticket_id);

ALTER TABLE similarity_matches ADD CONSTRAINT similarity_matches_not_self_match_check
  CHECK (ticket_id <> matched_ticket_id);



CREATE INDEX tickets_status_idx ON tickets (status);
CREATE INDEX tickets_claimed_by_idx ON tickets (claimed_by_agent_id);
CREATE INDEX ticket_events_ticket_id_idx ON ticket_events (ticket_id);
CREATE INDEX tickets_embedding_idx ON tickets USING hnsw (embedding vector_cosine_ops);

COMMIT;