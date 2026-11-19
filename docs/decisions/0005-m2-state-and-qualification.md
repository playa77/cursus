# ADR 0005: M2 package isolation and deferred qualification

- Status: accepted for source implementation; live acceptance deferred
- Date: 2026-11-19
- Basis: [WP-10–14](../cursus-implementation-roadmap-v0.1.1.md), D2 §§8–12
- Authorization: operator requested implementation through WP-14 and explicitly
  deferred user qualification and live testing until further notice.

## Context

M2 adds concurrent package execution, recovery, continuing debug sessions and
structured organizational conversations. The M0/M1 live gates remain pending.

## Decision

Keep package projections independent and reuse exact candidate/evidence gates.
Serialize integration per delivery group under the existing Store coordination
transaction. Revalidate target movement through a bounded merge, executed checks
and fresh review; conflicts or exhaustion park without unchecked publication. Queued dependents pin the committed group head. Separate groups
partition packages and reject dependencies across delivery outputs.

Keep recovery and command state durable, scoped to the original attempt. An
unknown outcome retains ownership. Publication recovery inspects the original
intent before authorizing any new mutation. No timeout proves process stop.

Continue local PostgreSQL/Git/executable-fixture verification. Prepare WP-14's
operator procedure and evidence checklist, but execute no live inference, VPS
changes, user qualification or milestone tagging. This supersedes any roadmap
instruction to qualify a live predecessor before independent source work.

## Consequences

Fixture evidence validates local contracts only. Live host boundaries, provider
capabilities and M2 acceptance remain unqualified. Independent lane projections
avoid sharing package candidates; a single shared candidate projection was
rejected because concurrent results could overwrite each other's evidence.
