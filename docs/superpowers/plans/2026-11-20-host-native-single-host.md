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
- Integration: 58 run, all error without `CURSUS_TEST_DSN` (disposable PostgreSQL).
  Unverified until a disposable database is available; this must be resolved before
  package C, which changes store-facing code.

## WP-A: Host execution replaces containers

Files: `src/cursus/execution.py`, `src/cursus/containers.py` (delete),
`src/cursus/bootstrap.py`, `src/cursus/config.py`, `src/cursus/repository.py`,
`src/cursus/runner.py`, `deploy/runner.example.toml`, tests under `tests/`.

- [ ] Add failing tests: child env is exactly the allowlist; cwd is the worktree;
  verifier uses the same path; process-group kill and no-orphan checks still hold;
  admission applies ceilings plus memory/disk pressure guards.
- [ ] Move the host spawn path out of the "test identity" seam into the production
  path; drop `runtime`, identity switching and UID 1000 assumptions.
- [ ] Extract the pressure guard from `Containers.fits` into a small admission helper.
- [ ] Remove `container_settings`, credential domains, Podman checks, ledger,
  `container_*` journal records and their recovery; keep the recovery constraints.
- [ ] Decide and record how project customization directories are handled
  (CLI clean-config flags versus explicit acceptance).
- Acceptance: unit suite green; runner starts against a fixture CLI with no Podman.

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
