# ADR 0006: Continuing debug and immutable conversation turns

- Status: accepted for WP-12/13 source implementation; qualification deferred
- Date: 2026-11-19
- Basis: D2 §§5, 8.2–8.5, T04/T06; roadmap WP-12/13; ADR 0005

## Context

A terminal pi turn does not end a debug attempt. Organizational conversations
must preserve revisions without conferring production or dispatch authority.

## Decision

Retain one RPC process while independent verifier claims inspect immutable Git
checkpoint refs. Continue commands carry failed evidence; finish commands bind
the exact passing checkpoint. Check the final workspace against that checkpoint
before independent review. Require executed failure evidence before accepting a
fix, and reset checkpoint state for a fresh debug attempt. Abandonment stops a
known live stale process on reconciliation and invalidates its verifier jobs.
Never relaunch a prior launch intent automatically.

Use closed JSON conversation results documented in the role prompts. Assign
question UUIDs on control, bind answers to the current open round and append
immutable transcript entries. Freeze advocate/critic/judge roles at admission;
they must use Claude/Codex/Antigravity distinctly, with the advocate on the author
CLI. Every seat invocation is fresh. A critic sees document/rationale/prior
upheld findings; later seat inputs add only the prescribed preceding results.
Validate author amendments before progressing; uphold major/blocker findings
through at most three rounds. Spec questions return to guided intake.

## Consequences

The same-attempt verifier loop and transcript are auditable through ordinary
operator reads/events. Fresh-process-per-debug-turn was rejected because it
would lose the required continuing RPC session. Free-form debate output was
rejected because it cannot safely drive transitions. Static role and capability
profiles still require separate real-provider qualification; fixture processes
prove neither provider tool restrictions nor deployed identity isolation.
