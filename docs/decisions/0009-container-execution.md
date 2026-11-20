# ADR 0009: Container execution on VPS-A

- Status: accepted direction; implementation and qualification tracked separately
- Date: 2026-11-20
- Authority: operator takeover instruction; PR #6 is rejected, not accepted precedent.
- Supersedes: account allocation, host identity and shared frontier limits in
  ADR 0004/0006 and D2 §4/§8.4; account-pool portions of rejected branch ADR 0008
  (`20831cffc28ff6452788409a3d5581800f6701ad`). ADR 0008 is absent from main.
- Acceptance: [finding matrix](../acceptance/container-execution.md).

## Context

Main is `38ea8ed`, including merged PR #5/WP-15/16. PR #6 is open and unmerged
at `20831cf`; its claimed acceptance and account management are rejected by the
operator. No discarded local repair is an input. Preserve the two hosts,
PostgreSQL/controller-only DB access, pull protocol, exact candidate gates,
independent review, publication recovery, immutable roles/prompts and native CLIs.

## Decision and rationale

Use rootless Podman 5.x, cgroup v2 and systemd delegation under one stable
unprivileged runner account. One container per agent session or verifier attempt;
continuing debug retains the container and pi RPC process across turns. No host
account allocation backend. Podman provides namespaces, container identity,
resource controls and descendant termination; Cursus owns durable intent,
inspection, stop/cleanup retries, admission and operator reporting. Agents receive
neither a runtime socket nor host management directories. Native binaries run
inside a pinned, operator-built image; no SDK, extension installer or meta-harness.

Use a read-only root, non-root container UID/GID 1000, keep-id mapping to the
runner's host UID/GID, dropped capabilities, no-new-privileges, private PID/IPC
namespaces, bounded tmpfs HOME and /tmp, and only the assigned workspace plus
explicit credential mounts. Shared host UID is not a claim of UID separation:
filesystem/PID namespaces and mount allowlists provide peer separation. Trusted
repositories remain mandatory; containers share a kernel. Production Git metadata
is a self-contained runner-owned store mounted read-only, without the publisher
credential or another session's cache. Capture and publication stay on the runner.

Persist a deterministic name and random ownership token before runtime creation,
then the immutable container ID before start. Inspect ID, name and token before
stop/removal. Missing objects are established with `container exists` (exit 1),
not arbitrary inspect failures. Recovery never starts a previously intended
execution: it stops the positively identified old container, removes it, and
reports interruption. An unattached native RPC channel cannot be reconstructed.
Unknown runtime state holds capacity; automatic retry can reclaim it when the
runtime recovers. Workflow abandonment alone releases no container or reservation.
Cleanup is durable, idempotent and independent of final delivery.

Every host specifies worker 1–4 and claude/codex/agy independently 1–2; no numeric
agent defaults. Verifier/repository retain separate capacities. All pi roles (including optional read-only scout/reviewer) use
the pi ceiling; this explicitly replaces their former competition in the shared
frontier lane. Independent review still gets a fresh container and immutable input.
A separate pi auxiliary ceiling was considered, but would add an unrequested
additional concurrency policy. Execution mode comes from qualified profiles,
never role names.

The pi ceiling applies to concurrent pi invocations.
Agent admission always leaves the configured verifier memory/CPU/task budget
available, including while debug waits. Repository operations have their own
bounded lane; resources are explicit policy, not measured CLI requirements.
FIFO pending local claims and rotating claim order prevent fixed-class priority
starvation. Unknown containers consume reservations until confirmed removed.

Credentials are persistent explicit native-auth-only mount directories, privately
owned by the runner. Never copy rotating login files, guess native paths or mount
whole host homes. A credential domain is exclusively leased to one container
until removal. Each configured concurrent provider session requires its own
qualified domain, with an explicit record establishing provider-side concurrency,
refresh ownership and recovery. Domains may not overlap. Native refresh writes
persist in place; no copy-back race. Unsupported multi-domain refresh blocks
activation at the requested ceiling; it never silently lowers concurrency.
Qualification is deferred to M3 end and cannot be replaced by an evidence string.

Setup stages immutable releases, validates supplied configuration, refuses
incompatible/preserved-but-different config and active upgrades, and activates an
explicit release only after drain/stop checks. Rollback uses the previous release
and its matching config; DB migrations must remain compatible or require restore.
No live host changes or provider qualification occur in this task.

## Alternatives and consequences

Rootful Podman offers simpler delegation but gives the runner host root; rootless
Podman is preferred to reduce management compromise consequences. Docker would
also isolate sessions but adds a daemon/socket authority boundary. Neither VMs,
Kubernetes nor a second execution backend is needed. Host account reuse retains
residue/identity problems and conflicts with the operator decision.

Images and layers share storage but need explicit disk reserve checks and manual
approved image retention; never prune unknown containers/images. No measured
memory, disk capacity, IOPS or throughput is asserted. Local fixture results do
not qualify user namespaces, actual mounts/cgroups, credentials or native provider
behavior on Ubuntu 26.04. Chromebook enrollment is later, not a delivery gate.

## Runtime references

[Podman create](https://docs.podman.io/en/v5.7.0/markdown/podman-create.1.html),
[inspect](https://docs.podman.io/en/v5.7.0/markdown/podman-container-inspect.1.html).
Local installed binary reports 5.7.0; rootless execution is blocked by the local
namespace sandbox. That is not qualification of Ubuntu VPS-A.

## Dependency license clarification

The operator explicitly clarified in this takeover task (2026-11-20): **allow OS
runtime helpers; keep Cursus libraries permissive**. Podman is Apache-2.0; the
Ubuntu passt rootless-network helper is GPL-2.0-or-later (installed package
copyright inspected). This exception applies to OS runtime helpers, not new
Cursus Python libraries, provider adapters or executable agent extensions. No
Python dependency was added. No host package was installed in this task.
