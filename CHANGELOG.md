# Changelog

Notable changes are recorded here using Semantic Versioning.


## [0.4.0] - 2026-11-20

Source implementation through WP-16. User qualification and live testing are
deferred to the end of M3 (WP-17); no milestone acceptance or tag.

### Added

- WP-15: bounded immutable artifact upload, claim-scoped input retrieval,
  authorized attachment downloads and durable verifier evidence logs. Upload
  intent/receipt replay gates final delivery; metadata conflicts fail closed.
- WP-16: server-rendered accepted design, private Serve identity/CSRF/origin
  checks, durable forms, committed SSE replay/reset, real PR/evidence handoff,
  local pinned htmx, persistent light/dark/OS themes and accessible log controls.
- Add event retention watermark migration 002 and committed browser projections.
- ADR 0007 records M3 artifact/browser decisions and the operator's accepted
  design and qualification deferral until the end of M3.

## [0.3.0] - 2026-11-19

Public-source M2 implementation. User qualification and live testing are deferred
until further notice; no M2 tag or acceptance claim.

### Added

- WP-09: live M1 qualification procedure, per-boundary evidence checklist and
  explicit operator-input gates. Qualification remains unrun; no M1 tag.
- WP-10: validated package DAGs and independent delivery groups; parallel runner
  tasks, per-package candidate/evidence state, serialized integration and dependent
  dispatch from committed heads. Conflicting patches park safely; target drift triggers bounded merge, fresh
  verification and review before publication.
- ADR 0005 records the implementation scope and explicit live qualification deferral.
- WP-11: original-attempt commands, cancel/unknown/abandon guards, lost-grant and
  lost-ack replay, boot-change stop evidence, bounded interrupted retries and
  read-only publication reconciliation. Includes reachability projection without timeout-based ownership release.
- WP-12: continuing pi RPC debug turns, immutable checkpoint refs, separate
  verifier claims, durable continue/finish commands and exact passing-checkpoint
  review/PR handoff. Local tests execute a failing then passing check in one
  process and confirm cancellation. Concurrent workers lease distinct configured
  identities; the second identity requires its own measured profile.
- WP-14: prepared real phase/recovery/debug/debate acceptance procedures and
  private evidence fields. User qualification and live testing remain deferred;
  no VPS/provider calls or M2 tag.
- WP-13: revision-bound guided interviews, required-answer admission, fixed
  three-frontier-seat debate, immutable per-seat transcripts, validated author
  amendments, spec-question round trips and the three-round unresolved-blocker
  cap. Direct intake and bounded scout behavior remain available.


## [0.2.0] - 2026-11-19

Public-source M1 implementation; live M0/M1 qualification is pending. No release
tag or production-readiness claim is implied.

### Added

- WP-08: wired single-package planning, production, pinned verification,
  independent review, staged phase checks, durable intents and confirmed PR
  handoff. Invalid/missing evidence and target drift park before publication;
  negative verdicts consume at most two fresh repair attempts.

- WP-07: direct pinned CLI execution with explicit child environments, RPC/JSONL
  framing, bounded process groups, real verifier evidence and strict review.

- WP-06: runner-owned Git worktrees, pinned blob reads, exact candidate/stage
  refs, conditional integration updates and conservative exact PR lookup.

- WP-05: generation-scoped runner reconciliation, claims and event sequence
  ingestion, authenticated transport, exclusive hash-chained fsynced journal.

- WP-04: strict startup settings, pinned role/prompt release, private operator
  socket, durable code intake/status and offline-discoverable CLI commands.

- WP-03: PostgreSQL migrations, ordered transactions, atomic idempotency and
  committed reads/wakeups; disposable-database integration checks.

- WP-02: public control/runner provisioning examples, an explicitly unqualified
  capability worksheet, host/identity/tailnet procedures and a qualification log.
- ADR 0002 keeps private deployment inventory and live evidence operator-local.
  Live M0 provisioning/authentication checks and the release tag remain deferred.

## [0.1.0] - 2026-11-19

### Added

- WP-01: installable Python 3.12+ baseline with offline help/version, strict
  contract primitives, canonical JSON and request digests, and disposable tests.
- Hash-locked prescribed dependencies and build tools with permissive license
  evidence; ADR 0001 records the package and contract boundary.

This package version is a bootstrap baseline. It is not a qualified M0 release.
