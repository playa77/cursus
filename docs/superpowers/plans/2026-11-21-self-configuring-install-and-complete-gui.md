# Self-configuring installer and complete GUI: plan

**Goal:** `./install.sh` yields a running service; the website exposes the complete application logic and every
operator-modifiable setting. Decisions: [ADR 0018](../../decisions/0018-self-configuring-install-and-complete-gui.md).

**Constraints:** no new dependency; no live inference, login or host installation; preserve gates, review,
publication recovery and pinned roles; no isolation claim; branch `claude/dazzling-pasteur-a5hob3`; no PR.

## Baseline (2026-11-21, commit `c4671d7`, CPython 3.13.18, locked venv, disposable PostgreSQL 16)

- Unit 80 run; 1 error until the package is installed in the venv (`test_installed_entry_point_and_module`).
  After `pip install --no-deps .` into the venv: 80/80.
- Integration 63/63 (PostgreSQL run as the `postgres` user; tests as root).

## Work packages (each leaves the suites green and is committed separately)

- **WP-E0** this plan and ADR 0018.
- **WP-E1 Foundation.** `cursus/tomlwrite.py` (production TOML writer, replaces the test helper); roles load
  with `qualified` state and submission is refused for unqualified roles; `cursus/admin.py`: validated atomic
  saves with backups, roles commit and pin, pending-restart detection, setup checklist, preflight, restart
  request, repository enrollment guard. Acceptance: round-trip tests for the writer; every save validated by the
  real loader; a failing candidate changes nothing on disk; roles save produces a commit and the new pin.
- **WP-E2 GUI.** Settings pages (access, capacity, resources, limits, publisher, repositories, roles, prompts,
  history), System page (deployment, drain/reopen, preflight, restart), setup checklist on the overview, no
  dead ends in intake, richer phase page. Acceptance: HTTP-level tests through the real browser surface (identity,
  Origin, CSRF, validation errors re-render the form, saves land on disk, pending-restart signal, restart refusal
  while busy); screenshots inspected in light and dark.
- **WP-E3 Installer.** Full derivation, Tailscale detection, sudo PostgreSQL step, linger, enable+start,
  readiness, completion of existing configs. Acceptance: temporary-home tests with recorded/simulated system
  calls; installer output plus the real loader accept the produced config.
- **WP-E4 Release.** README/runbook/architecture, CHANGELOG, version 0.8.0, full suites, handoff.

## Out of scope

Hot reload; verifying a GitHub token online; Tailscale Serve provisioning; installing PostgreSQL or the CLIs;
signing in to a CLI; selecting models.
