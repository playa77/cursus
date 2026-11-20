# ADR 0015: Installation ends before manual native login

- Status: superseded by [ADR 0016](0016-host-native-single-host.md); its rule that the installer never drives authentication is retained
- Date: 2026-11-20
- Authority: operator instruction after the installed image built successfully but the installer-launched Claude login failed: “at that point just say you finished install and remind me to login into all the cli's.”
- Supersedes: ADR 0011's installer-driven login, model selection and authenticated native-check workflow. Runtime qualification and isolation requirements remain.

## Context

Building the four native CLI installations succeeded. Setup then launched a
native login and treated its failure as an installation failure. Authentication
is an operator-controlled activity; installation must finish without driving it.

## Decision

Fresh worker installation ends after image creation and persistent native-state
domain preparation. Save choices privately as `/etc/cursus/runner.pending.toml`,
report native CLI installation complete, and remind the operator to log into
Claude Code, Codex CLI, Antigravity and pi themselves. Do not launch a login,
select/read models, request inference consent, run authenticated probes or wait
for the operator to complete authentication. Reruns reuse the cached image and
pending choices, without rewriting them or restarting questions.

A pending record is not a runtime config or successful login attestation. Do not
generate a qualified capability profile, pairing output, stage or activate a
fresh worker from it. Complete prepared deployment configurations retain their
existing separate staging/activation path. Existing services/configs are not
replaced by this change. Operator logins must use the installed runtime image
and persistent native-state domains; unrelated host installations do not populate
them. No credentials are copied and no provider fallback is introduced.

## Rationale and consequences

Treating login as an installer step was explicitly rejected. Silently bypassing
runtime readiness checks and marking an unauthenticated deployment ready would
misrepresent completion. Separating successful native installation from later
runtime configuration honors the request without manufacturing qualification.
The installer does not automatically complete later qualification/activation on
rerun. Existing manual prepared-profile deployment remains supported.

## Acceptance

Regression tests prohibit login, selection, inference and session calls from the
native installation entry point; verify pending-file creation/preservation and
no final worker config; and verify the guide stops before pairing/secrets,
staging or activation. Retain existing complete-config/controller behavior.
No host login or provider inference is required for these fixture checks.
