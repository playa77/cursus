> **Obsolete (ADR 0016):** describes the removed 0.6.0 container/two-host design. Rewritten in work package D.

# Ubuntu 26.04 deployment and release activation

Revision 2026-11-20-r4. New deployments start with the single
[`install.sh`](../install.sh) entry point and [README quick install](../README.md#quick-install).
The per-host wrapper examples below are the lower-level compatibility interface;
they assume prepared source/config/wheels. The unified installer performs that
bootstrap and calls the same staging/activation engine. Native image installation,
login guidance and generated pairing/profile metadata now follow
[ADR 0011](../docs/decisions/0011-native-install-and-login.md); the operator-built
image/profile discussion below is the advanced manual alternative, not a
first-time prerequisite.

[ADR 0009](../docs/decisions/0009-container-execution.md)
supersedes host execution accounts and rejected PR #6. This is a source delivery;
**do not provision or qualify hosts during design implementation**. Live user,
runtime and provider qualification remains at M3 end. Chromebook enrollment is
later. Only the operator authorizes real installation and provider probes.

## Required host inputs

VPS-A has 6 vCores/12 GB and runs rootless Podman **5.x**, pinned to the exact
installed version in `containers.version`, under one stable `cursus-runner`
service account and its lingering systemd user manager. cgroup v2, delegated
memory/CPU/PID controls, subordinate UID/GID ranges and an approved local image
are mandatory. VPS-B has 4 vCores/8 GB and runs the controller, PostgreSQL 16+,
private browser and artifacts. No local model server or GPU. No disk sizing or
throughput is inferred from these specifications.

Use a reviewed clean source commit, offline wheelhouse matching
`requirements.lock`, and complete host-local schema-2 TOML. Setup refuses schema
1 and conflicting settings. The templates deliberately have **no numeric agent
concurrency or hardware policy defaults**. Set pi 1–4 and each of Claude, Codex,
Antigravity 1–2 independently on both hosts; verifier/repository retain separate
single lanes. Configure explicit resource budgets/reserves based on policy and
later measurements, rather than claiming that every maximum fits together.

Build/import a trusted image with a pinned local `sha256:` image ID. It must
contain `/usr/bin/sleep`, native `pi`, `claude`, `codex`, `agy` and the enrolled
build/test binaries/dependencies at their qualified absolute paths. Qualification
binds that image, literal argv/transport/tool behavior and profile digest. Image
creation, vendor installation and extension enrollment are not guessed by the
installer. Images must contain no private credentials or automatic executable
extensions. Cursus uses `--pull=never`, ignores declared image volumes, replaces
the image entrypoint and clears image environment before adding its allowlist.

Provision native authentication opaquely into explicitly declared private,
runner-owned **auth-only directories**, with disjoint source paths per concurrent
credential domain. These are the only persistent session mounts; no whole host
HOME, runtime socket, publisher credentials, runner state or shared cache. No
native path is assumed by source. A domain is exclusively leased until its
container is confirmed removed. Refresh writes persist in place; there are no
login-file copies or copy-back races. Private qualification must establish whether
the provider supports the requested concurrent domains, token rotation, expiry,
renewal and recovery. If not established, activation fails at that requested
ceiling; Cursus never reduces it or rotates identities to bypass a restriction.
An evidence reference in TOML is not itself proof. No live credentials are needed
for the source tests.

VPS-B's local peer-auth role is `cursus-control`, database `cursus`; an operator
provisioned private DSN file may use `postgresql:///cursus?host=/var/run/postgresql`.
Only controller code connects to coordination PostgreSQL. The runner has no DSN.
Keep config/secret files private to the corresponding stable service account.
Paths in config must match that host's prepared storage; never copy a developer
agent credential or whole environment. Existing clients consume secrets opaquely.

## Plan and stage (later, under deployment authorization)

```sh
sh deploy/setup-worker.sh --release FULL_REVIEWED_COMMIT --dry-run
sh deploy/setup-controller.sh --release FULL_REVIEWED_COMMIT --dry-run
# Supply a complete host-local config to validate the concrete plan:
sh deploy/setup-worker.sh --release FULL_REVIEWED_COMMIT --config /absolute/runner.toml --dry-run
# Authorized intended host only; stage without activation:
sudo sh deploy/setup-worker.sh --release FULL_REVIEWED_COMMIT --config /absolute/runner.toml --wheelhouse /absolute/wheels --apply
sudo sh deploy/setup-controller.sh --release FULL_REVIEWED_COMMIT --config /absolute/control.toml --wheelhouse /absolute/wheels --apply
```

Each script installs the small host prerequisites and a stable service account,
then builds an immutable source/venv/wheel/config release under
`/opt/cursus/releases/<commit>-<config-sha256-prefix>`. Source/config changes get a
new directory; the installed code is never replaced in place. Completed identical
stages are reusable. A partial stage is retained with an explicit named-path
failure; inspect it before retrying rather than deleting arbitrary installation
state. Existing configuration is never silently retained in place of supplied
bytes. Unconfigured dry-runs describe missing prerequisites and cannot activate.
No package download concurrency, CLI login, provider calls, Tailscale enrollment,
ACL/firewall changes, Funnel or public listener is introduced.

## Drain, activate and rollback

A staged release is not active. For an existing installation the controller
activation requests a durable drain through the operator socket, then refuses
until unresolved attempts and queued jobs are zero. Finish current phases before an incompatible
role/profile migration: queued invocations retain their original qualification;
they must not be silently rewritten to a new profile. A worker activation queries
the authenticated controller and requires drain/zero unresolved attempts and queued jobs plus an
empty local lifecycle ledger. It cannot turn workflow abandonment into process
termination. Native credential qualification and source/install checks occur
before the old service is stopped. A prior root/system runner must be explicitly
drained and stopped before migrating to the user service; never run both.

```sh
# Select the exact staged config/release; same commands support rollback selection.
sudo sh deploy/setup-controller.sh --release FULL_REVIEWED_COMMIT --config /absolute/control.toml --activate-existing --apply
sudo sh deploy/setup-worker.sh --release FULL_REVIEWED_COMMIT --config /absolute/runner.toml --activate-existing --apply
```

Setup validates the complete config under the service account, pinned Podman
version, cgroup-v2/rootless/systemd support and local image availability. It creates
an aggregate execution slice and separate agent/verifier child slices from the
**same** config budgets used by admission. Agent saturation cannot consume the
verifier child slice's allocation. Rootless keep-id maps the service UID/GID to
non-root container 1000:1000; no per-session host accounts exist. Podman scopes
are managed by the service account's user manager, independently of the runner
transport process. On runner restart Cursus inspects/stops the old container;
it does not reconstruct or automatically relaunch an uncertain RPC execution.

Activation atomically switches `/opt/cursus/current`, reloads the appropriate
manager and starts the service. Diagnostics print the previous release path.
If post-switch startup fails, **keep intake drained**, inspect that service's
journal, and select the previous complete commit/config with the same activation
command. Rollback activation requires the same applied migration history. Migration 003
preserves old slot values, but main rejects unknown applied migrations: rolling
back to main requires a matching database backup/restore, not just a code switch.
The installer refuses a stage with missing/changed current migrations before
stopping the service. Keep drain and recover at the new release when an older
code/config/database set cannot be established safely.
A database migration in a future release may require a matching backup/restore.

Controller diagnostics: `systemctl status cursus-control` and
`journalctl -u cursus-control`. Runner diagnostics, through the service account's
user manager: `systemctl --user status cursus-runner` and
`journalctl --user -u cursus-runner`; set its `XDG_RUNTIME_DIR=/run/user/<uid>`
and `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus` when using `runuser`.
Inspect `cursus status --deployment` on the controller for durable drain and
unresolved count. A unit being active is not proof of authenticated readiness.
Wait for the browser's fresh reconciled runner contact, correct configured
ceilings, and no unexpected cleanup/uncertainty before qualification or reopening.
To reopen, submit `{"kind":"set_drain","enabled":false}` using the existing
operator `cursus action --input /absolute/nonsecret-drain-action.json` command.
Setup never silently reopens intake.

## Recovery and storage

The journal records container intent/token and immutable identity before launch;
the lifecycle ledger holds preparing/starting/running/stopping/cleanup/uncertain
state and the host numeric UID/GID/image. Loss of the ledger alone is recovered
from the journal, not treated as stopped. Same-boot and changed-boot recovery
inspect the actual runtime object. A name/token/ID mismatch never authorizes
stopping someone else's execution. Failed inspection/stop/removal keeps resources
and credentials unavailable; cleanup retries after recoverable failures. The
browser/runner health exposes the reason and age. Use supported service/runtime
diagnostics to correct the underlying failure, then let automatic retry reclaim
capacity; do not edit a ledger, delete a journal or abandon an attempt to fake stop.

Session root/HOME/tmp are disposable. Verified/acknowledged workspaces have a
durable deletion queue with automatic retry; a bounded cleanup backlog or low
configured disk reserve stops admission. The journal compacts retired requests,
retains unresolved ownership and replays bounded batches. Published Git objects
and pinned runtime image/cache storage still require approved retention under
WP-19; reserve-based admission is not a filesystem quota. There is no blanket
`podman prune`. Containers share a kernel and do not eliminate unsafe mounts,
credential leakage, exhaustion or orchestration defects. Intended-host isolation,
real resource behavior and native credential renewal remain unqualified here.
