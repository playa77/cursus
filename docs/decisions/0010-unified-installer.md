# ADR 0010: One fresh-host installation entry point

- Status: accepted for implementation; intended-host qualification remains open
- Date: 2026-11-20
- Authority: operator requested one installer, quick-install-first README, and a
  fix for the absent `~/cursus-source` failure after README PR #8.
- Extends: [ADR 0009](0009-container-execution.md), preserving its runtime,
  qualification, drain and migration boundaries.

## Context

The existing two thin host wrappers assumed a clean source checkout, offline
wheelhouse, accounts, private directories and finalized host configuration.
The README placed that path after lengthy preparation and described it as setup.
An operator beginning at its script section immediately hit a nonexistent source
directory. Those are installer responsibilities, not implicit user knowledge.

## Decision

Expose one public `install.sh` for both hosts, usable as a downloaded file or
through a pipe from any working directory. It obtains source when absent,
selects controller/worker, prepares packages/account/storage, obtains locked
Python wheels when no offline wheelhouse is supplied, guides private config,
then calls the existing immutable stage/activation engine. Questions read from
`/dev/tty`; caller stdin can contain the downloaded script. Dry-run/help never
clone, install, authenticate or modify files. Non-interactive mode fails rather
than prompting for missing prerequisites. Existing checkout/config/credential
state is never silently reset or overwritten.

The Python helper and existing per-host wrappers are implementation details and
compatibility interfaces, not separate scripts a new operator must find/run.
The launcher strips the inherited environment before privileged setup. It never
uses developer-agent credentials or runs provider inference. Native image,
auth-domain and permission qualification remain explicit activation prerequisites;
a missing qualified profile is an incomplete installation, never fabricated proof.

Guided control setup derives non-secret role tuples from the measured profile
and pins roles/prompts in a separate content-addressed local Git release under
`/etc/cursus/roles`. This uses the existing role-release verification contract
without editing public source, committing private host inventory or mutating the
role bytes used by another release. Manual/private committed role releases remain
supported. The capability digest binds the same bytes on both hosts.

## Acceptance and consequences

Check fresh-home/no-checkout execution, piped stdin with terminal-independent
non-interactive mode, whitespace/Unicode paths, no side effects in dry-run,
argument rejection, refusal to overwrite existing work, bounded hash-locked wheel
acquisition, private-file preservation and existing installer regression tests.
Both host plans and documentation examples must pass syntax/contract checks.
Actual Ubuntu package installation, systemd, native auth and provider/resource
qualification require intended-host tests; local mocks do not establish those.

A single wrapper that only selected the previous two scripts was rejected:
it would preserve the missing source/dependency/storage prerequisite failures.
Embedding vendor success settings or relaxing role/runtime checks to make a
one-line command appear successful was rejected because it would create unsafe
and unsupported activation. No new Python dependency or execution backend.
