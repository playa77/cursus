# Idle Installation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution.

**Goal:** Install and pair Cursus without selecting a repository or supplying GitHub credentials.

**Architecture:** Preserve existing empty-enrollment support and admission guards.
Remove enrollment from guided setup; skip publisher preparation for empty lists.

**Tech Stack:** Python standard library, TOML, Bash, unittest.

**Spec:** [ADR 0013](../../decisions/0013-idle-installation.md), recording the
operator's correction and requested PR.

## Global Constraints

- No new dependency, live inference, host installation or fabricated repository.
- Preserve saved configs, existing enrollments and credentials.
- Keep unenrolled work denied and retain drain/activation guards.
- Open a separate PR against main; do not merge.

## Review Focus

- Empty lists survive the actual serializer, pairing and config loader.
- Missing publisher files neither prompt nor get read for idle workers.
- Existing enrollments retain credential preparation.
- Empty enrollment never authorizes arbitrary work.
- Later enrollment uses the implemented configuration workflow.

## Task 1: Separate installation from repository enrollment

Files: `deploy/install.py`, `install.sh`, `src/cursus/templates/index.html`,
`tests/unit/test_install_entrypoint.py`, `tests/unit/test_native_setup.py`,
`tests/unit/test_idle_install.py`.

- [x] Add failing worker-configuration and credential-preparation tests that
  forbid repository, branch, test-command and publisher-token questions.
- [x] Verify failures, remove guided enrollment and guard publisher provisioning.
- [x] Cover empty pairing/configuration, retained enrollments and denied work.
- [x] Run affected tests and the complete unit suite.

## Task 2: Document, review and publish

Files: `README.md`, `CHANGELOG.md`, ADR 0013 and this plan.

- [x] Explain idle fresh installs and later enrollment using saved configs,
  publisher preparation and the existing guarded activation procedure.
- [x] Update script revisions and changelog.
- [x] Run syntax/diff checks, full unit suite and offline package build.
- [x] Review the branch; commit, push and open the requested PR at handoff.

## Execution record

- System-Python baseline: one packaging test fails because `/usr/bin/cursus`
  is absent. Create an isolated environment from the existing hash-locked
  offline wheelhouse, install this checkout and rerun the baseline.
- The operator already specified the intended idle behavior and requested its
  PR. Retain the existing later enrollment mechanism; add no new enrollment UI.
- The isolated environment baseline passed all 58 unit tests. Both original
  regression cases failed at the repository/token prerequisites before the fix
  and passed afterward. The new-run empty-state test likewise failed before
  its supporting template change and passed afterward.
- Delivered checks: all 65 unit tests, Bash syntax, diff whitespace checks, and
  an offline wheel build passed. No real Ubuntu/Tailscale/provider checks ran.
- Independent read-only branch review reported no actionable findings.
