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
- WP-C: the controller still supports the capacity-less legacy `frontier` slot
  path and `Runner` still tolerates `execution=None` for transport-only tests.
- WP-D: `deploy/cursus-runner.service` and `setup.py` still assume the rootless
  account, Podman, cgroup slice and subuid ranges; a service stop must kill the
  whole control group so orphaned CLI descendants cannot survive.

Not verified in WP-A: a real `cursus runner` process start (`bootstrap` refuses
root and no unprivileged account could run it here), any real CLI or login,
Antigravity session variables, and shared-login concurrency.

## WP-B: Roles, recipes and preflight

Files: `roles.toml`, `src/cursus/config.py`, `src/cursus/runtime_contracts.py`,
`src/cursus/execution.py`, `src/cursus/control.py`, a new recipes module,
`deploy/capabilities.example.toml` (delete), tests.

- [ ] Failing tests: roles file alone defines the required CLI set; recipes cover
  all four CLIs including output normalization already supported; unknown CLI
  version is reported, not guessed.
- [ ] Move fixed argv, transport, read-only and clean-config flags into source.
- [ ] Remove capability file/digest, `qualification`, image pin,
  `credential_concurrency`, `REPLACE_*` placeholders and `profile_digest` from
  contracts and the control/runner exchange.
- [ ] Add a read-only preflight (absolute path, version/help query; no inference,
  no login probe) and decide its command name.
- Acceptance: unit suite green; preflight never invokes a prompt path (tested).

## WP-C: One process

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
