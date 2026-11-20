#!/usr/bin/env bash
# Cursus installer entry point: intentionally disabled during the host-native rework.
# The previous installer built container images and paired two hosts; both are removed
# (ADR 0016). A small replacement is planned (work package D, docs/superpowers/plans/).
set -euo pipefail
cat >&2 <<'MSG'
The Cursus installer is being rebuilt (ADR 0016) and is not available in this revision.

Cursus now runs your already-installed, already-signed-in Claude Code, Codex CLI,
Antigravity and pi directly on one host. Until the new installer lands:
  - check your CLIs with:  cursus preflight --roles roles.toml
  - the configuration template is deploy/runner.host.example.toml
No installation was attempted and nothing was changed.
MSG
exit 1
