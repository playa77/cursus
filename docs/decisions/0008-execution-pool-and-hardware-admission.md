# ADR 0008: Sixteen pooled identities and operator-selected concurrency

- Status: accepted for implementation by explicit operator direction, 2026-11-20
- Supersedes: ADR 0004/0006 execution identity allocation and fixed capacity;
  D2 §4 two-worker/shared-frontier defaults and per-worker qualification records.
- Basis: brief topology (VPS-A 6 vCores/12 GB, VPS-B 4 vCores/8 GB), R02–R06,
  operator's final instruction: 16 accounts, workers 1–4, each frontier provider
  1–2, setup scripts for both VPSs. No user provisioning/testing requested here.

## Context

Account inventory, agent roles and execution concurrency were incorrectly coupled.
The implementation ignored configured capacities and had one shared frontier lane.
It also mirrored a potentially 2 GiB journal in memory, buffered Git archives,
serialized idle claims, and offered deployment worksheets without setup scripts.

## Decision

Provision exactly 16 additional unprivileged accounts, cursus-exec-01 through
cursus-exec-16, independently of role names. Keep one native login identity per
CLI and the existing verifier identity. Lease any free pooled account to each
agent/verifier execution; persist leases before launch. Preserve unknown leases
across restart; release only on locally confirmed stop/final or changed-boot stop
reconciliation. Never release an identity just because the operator abandoned
workflow authority while an old process may still exist.

Require explicit worker (1–4), claude/codex/agy (individually 1–2) configuration on
both hosts. Retain separate single verifier/repository/pi-scout lanes. There is no
numeric agent-concurrency default. Reconciliation rejects differing host settings.
Provider selection follows the committed role, never availability, spend or quota.
Polling empty lanes cannot delay ready work in another lane.

The root runner creates private per-attempt HOME directories, copies only
explicitly configured bounded regular native-auth files from that CLI's credential
identity, and runs the native CLI directly as the leased UID. No whole-home copy,
credential dump or profile per pooled UID. Original native auth is not rewritten;
renewal remains serialized at the CLI source login. Private execution copies are
removed after confirmed termination. Unsupported auth layouts remain explicit
capability limitations, not guessed paths or automatic extensions.

Use systemd transient service cgroups (no containers, VMs, provider adapters or
new Python dependencies) for aggregate child-process memory/CPU/task limits. Bind
execution units to the runner service lifecycle. Keep hardware memory/disk reserve
admission separate from concurrency ceilings. Retained unknown execution consumes
both its identity and resource reservation. Safety budget examples are not measured
CLI consumption or a guarantee that all configured maxima run simultaneously.

Flush live events independently of completion/heartbeats. Reserve terminal
journal space for the bounded execution inventory. Stream the journal, bound replay batches and archive extraction, and aggregate
browser usage in PostgreSQL. Keep retained unresolved records; retention/deletion
policy beyond safe temporary homes remains WP-19. Bound Store wait connections so
browser/mutation requests retain database capacity.

Supply explicit worker/controller Ubuntu systemd setup scripts with dry-run,
account collision checks, no-overwrite configuration, and opt-in service startup.
No credential generation/loading into a model, provider inference, Tailscale ACL
changes, public exposure, GitHub publication or production provisioning is part
of implementing these scripts.

## Alternatives and consequences

A single shared execution UID would be simpler but would lose peer isolation.
Per-execution containers introduce an unnecessary runtime/image lifecycle here;
VMs would duplicate operating-system overhead on the fixed hosts. The approved
16-account pool retains native execution and direct CLI contracts with bounded
scope. Built-in role bindings remain required but additional safe role definitions
are allowed. New workflow behavior remains repository-versioned source, not plugins.

Local fixture checks validate scheduling, leases, argv/resource wiring, setup
idempotency and existing workflows. Actual maximum throughput, provider-native
credential renewal and systemd isolation on intended hosts remain unmeasured.
The earlier live qualification deferral is unchanged; no work is shifted to the
operator to finish this source change.
