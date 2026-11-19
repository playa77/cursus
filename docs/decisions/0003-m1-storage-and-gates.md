# ADR 0003: Ordered M1 persistence and public-source qualification

- Status: accepted for repository implementation; live gates deferred
- Date: 2026-11-19
- Basis: D2 §§5.2, 8.1, 12; roadmap WP-03–09; ADR 0002
- Task: operator request to implement work packages through WP-09

## Context

The public repository has no live M0 attestation. The operator requested onward
implementation, while ADR 0002 excludes private provisioning from source work.

## Decision

Continue dependency-independent local implementation and disposable PostgreSQL,
Git and executable-boundary verification. Preserve the live M0/M1 gates; do not
label fixtures as real host, credential or provider evidence or create release
tags. No production deployment or live inference is part of this source change.

Keep foreign keys and queue/claim/publication uniqueness in relational columns;
store immutable protocol snapshots in JSONB to avoid a second serialization
model. Store owns transactions; Control supplies callbacks under the singleton
coordination lock. Events, requests and domain state commit atomically. Queries
use repeatable-read snapshots. SQL identifiers are internal allowlisted literals.

## Consequences

The local implementation can be reviewed and tested without private credentials.
JSONB semantic constraints remain the responsibility of strict contracts and
transaction guards. Live predecessor qualification is still required before
production use. A substitute SQLite store or fabricated host evidence would not
satisfy the approved PostgreSQL and qualification contracts.
