CREATE TABLE coordination (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
 cursor bigint NOT NULL DEFAULT 0 CHECK (cursor >= 0),
 drain boolean NOT NULL DEFAULT false
);
INSERT INTO coordination(singleton) VALUES(true);
CREATE TABLE request_keys (
 principal text NOT NULL, route text NOT NULL, request_id uuid NOT NULL,
 digest text NOT NULL, response jsonb NOT NULL,
 PRIMARY KEY(principal, route, request_id)
);
CREATE TABLE phases (id uuid PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE specs (
 phase_id uuid REFERENCES phases(id), revision integer CHECK(revision > 0),
 payload jsonb NOT NULL, PRIMARY KEY(phase_id, revision)
);
CREATE TABLE plans (LIKE specs INCLUDING ALL);
ALTER TABLE plans ADD FOREIGN KEY (phase_id) REFERENCES phases(id);
CREATE TABLE integration_lanes (
 id uuid PRIMARY KEY, phase_id uuid NOT NULL REFERENCES phases(id),
 group_id text NOT NULL, payload jsonb NOT NULL, UNIQUE(phase_id, group_id)
);
CREATE TABLE packages (
 id uuid PRIMARY KEY, phase_id uuid NOT NULL REFERENCES phases(id),
 plan_revision integer NOT NULL, package_id text NOT NULL, owner uuid,
 payload jsonb NOT NULL, UNIQUE(phase_id, plan_revision, package_id)
);
CREATE TABLE runners (id uuid PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, phase_id uuid NOT NULL REFERENCES phases(id),
 package_id uuid REFERENCES packages(id), lane_id uuid REFERENCES integration_lanes(id),
 step text NOT NULL, scope text NOT NULL, ordinal integer NOT NULL CHECK(ordinal > 0),
 slot text NOT NULL CHECK(slot IN ('worker','verifier','frontier','repository')),
 state text NOT NULL CHECK(state IN ('queued','claimed','done','canceled')),
 creation_cursor bigint NOT NULL, payload jsonb NOT NULL,
 UNIQUE(phase_id, step, scope, ordinal)
);
CREATE INDEX jobs_queue ON jobs(state, slot, creation_cursor);
CREATE TABLE attempts (
 id uuid PRIMARY KEY, job_id uuid NOT NULL UNIQUE REFERENCES jobs(id),
 phase_id uuid NOT NULL REFERENCES phases(id), runner_id uuid NOT NULL REFERENCES runners(id),
 request_id uuid NOT NULL, ack bigint NOT NULL DEFAULT 0 CHECK(ack >= 0),
 status text NOT NULL, payload jsonb NOT NULL, UNIQUE(runner_id, request_id)
);
ALTER TABLE packages ADD FOREIGN KEY(owner) REFERENCES attempts(id);
CREATE TABLE commands (
 id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES attempts(id),
 issued_seq bigint NOT NULL, payload jsonb NOT NULL
);
CREATE TABLE events (
 cursor bigint PRIMARY KEY, phase_id uuid REFERENCES phases(id),
 attempt_id uuid REFERENCES attempts(id), source_seq bigint,
 kind text NOT NULL, time timestamptz NOT NULL DEFAULT clock_timestamp(),
 digest text, payload jsonb NOT NULL, UNIQUE(attempt_id, source_seq)
);
CREATE TABLE artifacts (
 id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES attempts(id),
 payload jsonb NOT NULL
);
CREATE TABLE publications (
 id uuid PRIMARY KEY, phase_id uuid NOT NULL REFERENCES phases(id),
 lane_id uuid NOT NULL REFERENCES integration_lanes(id), state text NOT NULL,
 payload jsonb NOT NULL
);
CREATE UNIQUE INDEX publication_unresolved ON publications(lane_id)
 WHERE state = 'pending';
