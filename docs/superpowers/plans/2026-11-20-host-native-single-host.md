# Host-Native Single-Host Reorganization Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution.

**Goal:** Run the already-installed, already-signed-in Claude Code, Codex CLI,
Antigravity and pi directly on one host in one process, and delete the image,
container, pairing and capability-generation machinery.

**Architecture:** [ADR 0016](../../decisions/0016-host-native-single-host.md).
Four work packages, each leaving the unit suite green and each committed
separately. The version moves to 0.7.0 only in package D.

**Tech Stack:** Python standard library, FastAPI/asyncpg (unchanged), TOML, Bash, unittest.

## Global Constraints

- No new dependency, no live inference, no host installation, no real login.
- Preserve the workflow gates, independent review, publication recovery and
  immutable roles/prompts. Do not weaken drain/activation guards.
- No isolation claim anywhere in code, docs or installer output.
- Never read, copy or print CLI credentials or `HOME` contents.
- Branch `claude/serene-bell-aigsei`; no PR and no merge without a request.

## Baseline (2026-11-20, commit `c636b78`, CPython 3.13.18, isolated venv from `requirements.lock`)

- Unit: 79 run, 78 pass. One error: `test_bootstrap.test_installed_entry_point_and_module`
  needs the package installed in the venv; not a source defect.
- Integration (disposable local PostgreSQL 16, run as root because no unprivileged
  account could reach the scratch area): 58 run, 29 bad (15 failures, 14 errors),
  reproduced on a clean export of `c636b78`. Most are the legacy privilege path
  refusing uid 0 (`identity_boundary`); the baseline is therefore not a statement
  about the legacy path on a non-root host.

## WP-A: Host execution replaces containers (implemented; see "Re-scope" below)

Files: `src/cursus/execution.py`, `src/cursus/containers.py` (delete),
`src/cursus/bootstrap.py`, `src/cursus/config.py`, `src/cursus/repository.py`,
`src/cursus/runner.py`, `deploy/runner.example.toml`, tests under `tests/`.

- [x] Failing tests first (`tests/unit/test_host.py`): child env is exactly the
  allowlist; cwd is the worktree; process-group stop, restart recovery, PID-reuse
  and boot-change safety; admission by ceilings plus memory/disk pressure guards.
- [x] New `src/cursus/host.py` (`HostRuntime`): ceilings, pressure guards, durable
  process ledger (`execution_intent`/`execution_identity`/`execution_removed`),
  positively identified group termination, per-attempt `TMPDIR`.
- [x] `Execution` takes `(profiles, runtime)`; identity switching, `allow_test_identity`,
  UID 1000 and binary-digest pinning removed; every child, including verifier
  checks, goes through `HostRuntime.spawn`.
- [x] `Runner`, `Repository` (always self-contained clones), `bootstrap` and
  `config` (`[execution]` section, `execution_settings`) use the host runtime.
- [x] Customization directories (decided): no masks. The only control is each
  profile's `clean_config_argv` already applied on every invocation; its effect on
  real installed CLIs is unverified and is checked in WP-B.
- [x] Fixed a race exposed by direct spawning: a command exiting before reading
  stdin (a fast-failing check) raised `ConnectionResetError` out of `Execution`.
- Acceptance results: unit 93/93, integration 58/58 (as root; see baseline).

### Re-scope (recorded during WP-A)

The installer, stage engine (`deploy/setup.py`) and about 30 installer tests are
coupled to `cursus.containers`, `config.container_settings` and the `[containers]`
template. To keep this package reviewable and the suite green, these are
**deferred to WP-D** instead of deleted here: `src/cursus/containers.py`,
`config.container_settings`, `deploy/native/*`, `deploy/native_setup.py`, the
resource-prompt code, `deploy/runner.example.toml` (now marked legacy) and
`tests/unit/test_containers.py` (legacy header). Consequence until WP-D: the
installer and stage engine still emit and validate the 0.6.0 container schema,
which the runner no longer loads. The new contract is
`deploy/runner.host.example.toml`. The branch is not releasable until WP-D.

Carry-overs for later packages:
- WP-B: `capabilities_file`/`capabilities_digest`, `qualification`, `profile_digest`,
  `credential_concurrency` (no longer enforced, still required by `capability()`),
  and verification of every CLI's `clean_config_argv` against real installs.
- WP-D: `deploy/cursus-runner.service` still assumes the rootless
  account, Podman, cgroup slice and subuid ranges; a service stop must kill the
  whole control group so orphaned CLI descendants cannot survive.

Not verified in WP-A: a real `cursus runner` process start (`bootstrap` refuses
root and no unprivileged account could run it here), any real CLI or login,
Antigravity session variables, and shared-login concurrency.

## WP-B: Roles, recipes and preflight (implemented)

Files: `roles.toml`, `src/cursus/config.py`, `src/cursus/runtime_contracts.py`,
`src/cursus/execution.py`, `src/cursus/control.py`, a new recipes module,
`deploy/capabilities.example.toml` (delete), tests.

- [x] Failing tests first (`tests/unit/test_recipes.py`): exact argv per CLI and
  tool set, authority limits by CLI/tier, value hygiene, resolution, preflight
  (only `--version`/`--help` run), the `cursus preflight` command.
- [x] New `src/cursus/recipes.py`: fixed argv, transport, read-only and clean-config
  flags live in source and are built from the role (cli, model, reasoning, provider,
  tools). pi's mode comes from the role's tools (write tools: rpc; read-only: json
  print with the prompt as an argument), never from a role name.
- [x] Removed from contracts, `Control`, the runner config and `roles.toml`: capability
  file/digest, `profiles`, `qualified_roles`, `credential_concurrency` enforcement,
  `profile_digest` (roles `schema_version` is now 2). `Execution(clis, runtime)`
  holds installed absolute paths; a missing CLI fails the job with `cli_missing`.
- [x] `cursus preflight --roles roles.toml [--config runner.toml]`: resolves each CLI
  the roles use (PATH search or `[execution.clis]`, `antigravity` accepted for
  `agy`), runs version and help queries only, and checks every option the recipe can
  emit is advertised. Signed-in state is not and cannot be checked.
- [x] `deploy/capabilities.example.toml` deleted.
- Acceptance results: unit 110/110, integration 58/58.
- Verified against a real install: Claude Code 2.1.330 `--help` advertises every
  option in its recipe (including `--safe-mode`, whose documentation says it disables
  project/user customizations while auth, model and built-in tools work), and the
  real preflight passed. NOT verified: codex, agy and pi recipes (not installed
  here; carried over from 0.6.0), any CLI's behavior under a real login, and whether
  `--ignore-user-config`/`--ephemeral` (codex) leave its login intact.

Carry-overs: `config.capability()`, `deploy/native_setup.profiles` and the guided
installer's profile-driven role derivation remain as legacy until WP-D;
`ops/runbook.md` and the README still describe the capability file.

## WP-C: One process

### WP-C0: purge the dead installer stack (re-scope, pulled forward from WP-D)

The legacy installer, stage engine and about 50 tests exist only to build container
images, pair two hosts and write the two-process configuration; `deploy/setup.py` also
calls the HTTPS transport and the old `load('runner'|'control')`. None of it can work
under the single-process contract, so keeping it only forces every WP-C commit to
carry its dependencies. Removed in C0: `deploy/install.py`, `native_setup.py`,
`setup.py`, `setup-*.sh`, `deploy/native/*`, `deploy/runner.example.toml`,
`src/cursus/containers.py`, `config.container_settings` and `config.capability`, and
their tests (unit 110 -> 56; only tests of deleted code were removed).
`install.sh` is now a stub that explains the situation and changes nothing; README,
ops docs and the acceptance matrix carry an obsolete banner; ADRs 0009, 0011, 0014
and 0015 are marked superseded (0010 and 0012 partly). WP-D no longer deletes these;
it writes the replacement installer, systemd unit, README and ops docs.

### WP-C1: the single process (implemented; design checkpoint first)

Finding: the runner/control protocol is transactional and idempotent (reconcile with
dispositions, `jobs/next` claims keyed by request id, sequence-checked event digests,
commands carried on heartbeats, artifact upload/download). Its *semantics* are what
recover a crash between a database commit and a journal write, which an in-process
design still suffers. Only the *transport* is redundant. So C1 keeps the protocol and
the runner journal, and replaces HTTPS with an in-process transport calling
`Control.runner_request` and `artifact_control.upload/download` directly.
Removing the protocol itself (runner calling the store directly) is a non-goal: it
would rewrite the recovery guarantees for no operator benefit.

Implemented:
- [x] `LocalTransport` (in `runner.py`) replaces `HTTPS`/`NoRedirect`: calls
  `Control.runner_request` and `artifact_control.upload/download` in process, round-trips
  values through strict JSON as the wire did, and bounds the runner's share of the
  database pool. Control's real Problem codes now reach the runner (HTTP had flattened
  them to `transport`); a database failure raises out of the runner and ends the process
  for a supervised restart.
- [x] Removed the runner HTTP routes, the bearer guard and digest, `Runner`'s
  `intake_denied` path, `service.origin/bearer_file/spool_root`, `runner.tailnet_node`,
  the legacy capacity-less slot defaults, the long-poll branch and the `long_poll_seconds`
  and `runner_spool_bytes` limits. `capacity` is required everywhere, and the runner
  requires an execution (host runtime); the no-execution mode served only transport tests.
- [x] One config: `process_kind = "serve"`, `schema_version = 3`
  (`deploy/cursus.example.toml`, validated through the real loader in tests). One command:
  `cursus serve` replaces `control` and `runner`. `bootstrap.run()` supervises
  maintenance, both HTTP surfaces and the runner; any component ending ends the process.
  `check_identity` refuses root and a user other than `service.user`.
- [x] Deleted both two-process units and templates; the replacement unit is WP-D.
- Acceptance results: unit 57/57, integration 63/63, including an end-to-end test of
  `run()` (one process, real operator socket, journal, host runtime, PostgreSQL schema,
  fixture CLIs and Git remote) that delivers a phase and removes its socket on stop.
- NOT verified: a real `cursus serve` start as a non-root user (the identity check is
  unit-tested and `run()` is exercised, but no unprivileged account could launch the
  process here), SIGTERM handling of the real process, any real CLI or login, and the
  browser surface behind a real reverse proxy.
- Carry-overs for WP-D: installer, systemd unit (must kill the whole control group on
  stop so orphaned CLI descendants cannot survive), README and ops rewrite, normative
  spec revision, version bump. Cosmetic: workflow steps still name the placeholder lane
  `frontier` before the control plane maps it to the role's CLI lane.

Files: `src/cursus/runner.py`, `src/cursus/transport.py`, `src/cursus/http.py`,
`src/cursus/control.py`, `src/cursus/bootstrap.py`, `src/cursus/config.py`,
deploy units, tests.

- [ ] Design checkpoint first: map every runner<->control exchange and every
  journal record to the retained recovery constraints; record what the journal
  still needs to guarantee. Obtain a disposable PostgreSQL for integration runs.
- [ ] Replace the HTTPS pull transport with in-process calls into existing
  transition functions; remove bearer, digest files, pairing and heartbeat-loss logic.
- [ ] Merge the two service configurations and the two systemd units into one.
- Acceptance: unit and integration suites green against a real disposable
  PostgreSQL; crash-recovery tests prove no double launch and no lost candidate.

## WP-D: Installer, docs, release

Files: `install.sh`, `deploy/*`, `README.md`, `ops/*`, `docs/*`,
`CHANGELOG.md`, `pyproject.toml`, `tests/unit/test_*install*.py`.

- [ ] Delete `deploy/native/*`, `deploy/native_setup.py`, pairing and Tailscale
  discovery, resource prompts and the per-host wrapper scripts.
- [ ] Installer: prerequisites and preflight, hash-locked packages, PostgreSQL
  access, private config, one service unit. Keep `/dev/tty` prompts, no-op dry-run
  and no-overwrite behavior.
- [ ] Rewrite README (prerequisite first, plain isolation statement) and ops docs;
  revise the design and technical specification for the new topology/contracts.
- [ ] Bump to 0.7.0 with a full changelog entry; mark superseded ADRs.
- Acceptance: whitespace/Unicode paths, dry-run no side effects, argument
  rejection, existing-work preservation; full suites green. Real-host install,
  actual CLI sign-in state, Antigravity keyring variables and shared-login
  concurrency remain unverified until tested on an intended host.

## Review Focus

- No path launches a CLI without the allowlisted environment.
- No code or text claims sandboxing or verified sign-in.
- Recovery behavior after crash is unchanged in observable outcomes.
