# ADR 0007: Immutable evidence transfer and private browser control

- Status: accepted for WP-15/16 source implementation; live acceptance deferred
- Date: 2026-11-20
- Basis: D2 §§5–10, T07/T09; roadmap WP-15–17; ADR 0005/0006
- Authorization: operator requested source implementation through WP-16, accepted
  the design handoff, and deferred user qualification and live testing to M3 end.

## Context

M3 must expose existing committed workflow state and genuine downloadable
verification evidence. A network interruption must not trigger reexecution or
make incomplete bytes readable. The accepted static reference contains synthetic
states that cannot become deployed state or authority.

## Decision

Reserve immutable artifact metadata and phase budget under the coordination
transaction, stage/hash/fsync bytes outside it, then recheck claim ownership and
commit ready metadata. Persist runner upload intent and exact evidence bytes
before final spool entries; replay transfers before sending finals. A lost receipt
reuses the same file ID and digest. Flat server-computed paths, no-follow opens,
atomic links and held verified descriptors protect immutable downloads. Staged
reservations survive interruptions and count against the phase cap; maintenance
of orphan reservations remains WP-19. Verifier results require ready owned logs.

Use a distinct Serve-facing browser application on the configured loopback
listener alongside bearer-authenticated runner routes; keep the Unix socket JSON
operator contract. Browser authority requires the exact single Serve login.
Use process-lifetime signed session/CSRF tokens, exact origin, host-only Secure
HttpOnly SameSite cookies and local assets. Restart invalidates browser sessions;
reload creates a fresh token, and action UUIDs preserve idempotency. Replay only
committed SSE events, advancing by emitted event IDs rather than a page high-water
cursor. Retention watermark or future cursors reset to a new snapshot.

Port the accepted reference's original CSS and shell, omit all synthetic runtime
states and prototype-only assets, and initially follow OS theme with persistent
operator override. This is the reversible existing-preview default, with the
accepted violet accent. Vendor pinned htmx with its permissive license; no build.

## Consequences

Local PostgreSQL/Git/process/HTTP fixtures prove contracts, not actual Serve
header isolation, provider permission or device usability. WP-17 at the end of
M3 must qualify the deferred M0/M1/M2 and browser checks; no tags or production
readiness claims follow from source completion. This supersedes ADR 0005's
indefinite deferral timing. An in-memory upload registry and client-rendered
workflow authority were rejected because neither preserves durable state.
