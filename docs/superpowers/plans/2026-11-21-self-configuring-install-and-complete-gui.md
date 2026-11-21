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

## Results (2026-11-21)

| Package | Commit | Checks run |
| --- | --- | --- |
| WP-E0 | `fc922f1` | n/a (documents) |
| WP-E1 | `e8398f5` | unit 108/108, integration 64/64 |
| WP-E2 | `ecf1b30` | integration 82/82 (18 new, through the real HTTP surface); every page inspected in Chromium, light and dark |
| WP-E3 | `665add2` | unit 130/130 (installer against simulated system calls; the real loader accepts its output) |
| WP-E4 | this commit | full unit and integration runs recorded in the handoff |

One defect found and fixed during WP-E1: a `qualified` flag inside role dicts reached the runner's strict job
validation and made the transport exhaust its retries; it now lives beside the roles (`unqualified_roles`).
The test PostgreSQL could not live in the scratchpad (the harness re-tightens its permissions so the `postgres`
user cannot reach it); it ran under `/var/tmp` and was removed afterwards.

Unverified: sudo PostgreSQL provisioning, `loginctl enable-linger`, `systemctl --user enable --now`, Tailscale
status parsing against a real tailnet, and the restart cycle under systemd. All were exercised only against fakes.

## Proposed WP-E5: conversation with the system (DEFERRED by the operator, 2026-11-21, until further notice)

Not to be started or scaffolded until the operator says otherwise. The decisions below stay open.

A read-only "Discuss" page: ask about project status, brainstorm a change, and turn an agreed change into a run.
Needs decisions: (1) which role/CLI/model answers, (2) what context it may see (phases, plans, evidence, git state;
repository file contents or not), (3) a per-conversation call and cost cap and a kill switch, (4) whether "turn into a
run" prefills the intake form or submits directly, (5) retention of transcripts. Design sketch: a `discussion` role
(read-only tools) invoked per turn with an assembled, size-bounded status digest; turns persisted as committed events;
no write tools, no network beyond the CLI's own; repository text delimited and labelled as untrusted data.

## Out of scope

Hot reload; verifying a GitHub token online; Tailscale Serve provisioning; installing PostgreSQL or the CLIs;
signing in to a CLI; selecting models.
