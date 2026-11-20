# Cursus host setup

Revision 2026-11-20-r1. Ubuntu Server 26.04, systemd and CPython 3.12+.
This supersedes the historical per-worker provisioning instructions in runbook.md.

VPS-A is the 6-vCore/12-GB runner host. VPS-B is the 4-vCore/8-GB controller host.
MyPC (Xubuntu 26.04) is a browser/SSH client; Chromebook enrollment is later.
No container engine, VM, frontend toolchain, local model server or GPU is required.

## Scripts and explicit concurrency

Run from the reviewed Cursus checkout. They can be invoked from any directory.
Both hosts must receive the same explicitly chosen counts. These examples use
maximum allowed counts; they are examples, not defaults or a throughput claim:

```bash
# Inspect without root, network, account, package or service changes:
./deploy/setup-worker.sh --workers 4 --claude 2 --codex 2 --agy 2 --dry-run
./deploy/setup-controller.sh --workers 4 --claude 2 --codex 2 --agy 2 --dry-run

# Run the corresponding command on each intended host:
sudo ./deploy/setup-worker.sh --workers 4 --claude 2 --codex 2 --agy 2
sudo ./deploy/setup-controller.sh --workers 4 --claude 2 --codex 2 --agy 2
```

Workers accept 1–4; each of Claude/Codex/Antigravity independently accepts 1–2.
There is no shared frontier limit. Pi scout/review, verifier and repository lanes
remain separately serialized. Sixteen available accounts never mean sixteen
simultaneous agents. Repository/verification subprocesses consume additional
resources and are not included in the ten-agent maximum.

Optional `--runner-id UUID --origin https://HOST.TAILNET.ts.net` fill common
non-secret deployment values. `--operator-login LOGIN` fills the controller's
exact Serve identity. No script changes Tailscale grants, Serve configuration,
public listeners, SSH policy or provider credentials. `--skip-packages` is for
hosts whose administrator has already installed dependencies. `--start` validates
the completed configuration before enabling the dedicated Cursus service; default
installation does not start Cursus or perform inference.

## What installation does

Both scripts install the hash-locked Python dependencies and application into
`/opt/cursus/venv`, stage their TOML and systemd unit, and report every operation
with UTC timestamps. A failed step stops with its context. Existing config,
capabilities, secrets and service units are preserved; changed units require an
explicit operator-managed upgrade, not a blind overwrite.

The worker creates these **16 additional reusable execution accounts**:
`cursus-exec-01` through `cursus-exec-16`. They have locked system accounts,
non-login shells, private homes and individual primary groups. It also creates
stable native credential identities `cursus-pi`, `cursus-claude`, `cursus-codex`,
`cursus-agy`, and the verifier identity. These are not role or agent instances.
Existing conflicting usernames/homes/shells/groups are rejected rather than
adopted. No actual account is created by a dry-run.

The controller creates `cursus-control`, `cursus-operators`, private artifact/DSN
roots, a local PostgreSQL role/database and a peer-auth DSN. PostgreSQL starts;
No Cursus service is started or restarted. No database is installed on the worker.

## Native credentials and private execution homes

Install approved native CLIs at fixed absolute paths on A and log in **once per
CLI**, under its stable credential identity. Do not log in sixteen times or copy
the developer agent's credentials. Configure each `cli.NAME.auth_files` as the
explicit relative regular native-auth files that this installed CLI requires.
No paths are guessed; the supported native layout is a capability input.

Before an execution, the root runner leases a free pool account and prepares a
private HOME for that attempt. It copies only the selected credential files to
that HOME with mode 0600, assigns the leased UID, and invokes the native CLI.
Files and values never enter prompts, logs, role snapshots or command arguments.
Each concurrent execution has its own writable state. Its state is not copied
back to the source login. Run native credential renewal on the stable source
identity serially; clients whose refresh semantics invalidate concurrent copies
must be qualified/fixed before enabling concurrency. Empty `auth_files` supports
clients requiring no native files; it does not assert successful authentication.

No per-pool-account capability profiles or native logins are required. Capability
qualification still binds the binary, model/provider/reasoning, exact tool set,
clean configuration, prompt transport and native auth behavior. Extra role names
are accepted; tier/tool rules still apply. New workflow behavior is ordinary
repository-versioned source, not an executable plugin system.

Unknown process outcomes retain the UID lease, private home and memory reservation
across restart. Abandonment invalidates workflow authority but does not prove a
process stopped. A changed boot proving stop releases the old lease. Never delete
the journal or reuse a quarantined UID manually to bypass this rule.

## Hardware bounds

Concurrency is an upper bound, not an instruction to overcommit memory. The
runner checks available memory, its reserved execution budgets and free disk
before admission. Resource pressure queues work without provider routing or
ownership expiry. A debug session still needs headroom for its independent
verifier; the budget must admit that combination.

The example resource settings reserve **2 GiB RAM and 2 GiB disk**, allocate up
to **2 GiB per worker/verifier** and **512 MiB per frontier execution**, cap each
execution at **100% CPU and 128 tasks**, and bound a repository snapshot at **1
GiB**. These are explicit editable safety policies, **not measurements** of a
vendor CLI or arbitrary project build. An oversized job can fail its cgroup cap
rather than bring down the host. Raising concurrency does not raise these caps.

The worker installer also stages `cursus-execution.slice`: one logical CPU is
left outside the aggregate execution quota (five cores on the intended six-core
A), memory is capped at host RAM minus the 2-GiB reserve, swap is disabled for
executions, and aggregate tasks are capped at 2048. Review this managed unit when
changing the example reserve policy. Every direct CLI/verifier process tree runs
in a transient service under that slice, with per-execution memory/CPU/task caps
and lifetime bound to `cursus-runner.service`. Process cleanup verifies the actual
unit; losing its systemd-run transport does not establish stop.

Native CLI environment is reset to the explicit allowlist even if the systemd
manager has additional defaults. The runner journal streams from disk rather than keeping all payloads in RAM;
replay sends at most 100 events per batch. Snapshot archives stream via bounded
temporary files. Active disk reserve monitoring stops execution at pressure;
this is not a filesystem project quota and can overshoot between checks. Retained
worktree/cache/artifact history still needs the WP-19 retention policy. Disk size,
IOPS, actual CLI memory, and project workload remain unmeasured; no maximum-load
or production-readiness claim follows from local tests.

## Activation and upgrade

Complete the private model/CLI settings, profile hash, native credentials,
publisher credentials and approved repository/check enrollment. Both hosts must
have matching `[capacity]`; reconciliation rejects mismatches. Deploy the
committed `roles.toml` and `prompts/` release on B at the configured path, then
set its commit. Startup checks only that exact root-owned Git directory as safe;
no wildcard Git trust is needed. Templates intentionally fail closed until filled.

Old `worker_slots`, `worker_profiles` per Unix user and shared `capacity.frontier`
are replaced by `execution_pool` and the new capacity lanes. Do not change an
active UID mapping or discard its lease history. Stop/drain old executions before
changing pool configuration; dispose of pre-upgrade unknown processes with
actual stop evidence. The update preserves PostgreSQL phase/job identities and
numbered migration history. A pi-scout role override may still be needed for its
different read-only argv/tools, but not per pool UID.

Installations preserve existing config on rerun, so upgrades must apply this
schema migration deliberately. Set the same chosen capacity on both hosts,
restart control, then runner and allow reconciliation. Enable private Serve on B
only with its exact origin/login and existing authorized tailnet policy. MyPC
opens that HTTPS address; it needs no agent installation. Chromebook is later.

Local automation validates scripts with fake account/package/systemd boundaries,
real temporary files, PostgreSQL, Git and executable CLI fixtures. It does not
provision a VPS, authenticate a real provider, or qualify the actual systemd
boundary. User qualification and live testing remain deferred to M3 end.
