# Changelog

Notable changes are recorded here using Semantic Versioning.

## [Unreleased]

Planned for 0.7.0; the version is not bumped until the installer work package lands.
The branch is not releasable meanwhile: the installer and stage engine still emit
the 0.6.0 container configuration, which the runner no longer loads.

### Added (work package D)

- Per-user installer (`./install.sh`, ADR 0017): runs as your own user (never root), builds a
  hash-locked venv from `requirements.lock`, creates private directories, scaffolds a separate role
  release git repo, writes a starting `cursus.toml` (only mechanical values filled; capacity, reserves,
  origin, login, role commit and repositories stay yours to choose), a local-socket DSN file, and a user
  systemd unit with `KillMode=control-group`. It never overwrites existing files, never starts a service,
  never signs in to a CLI. `--dry-run` changes nothing. The real venv, hash-locked install and package
  build were run once in a scratch home; systemd, PostgreSQL and CLI logins were not.
- Loading the config now names every unfilled `REPLACE_` value. `cursus preflight --config` no longer
  needs the reserve values. A config without `[[repositories]]` loads idle (ADR 0013); the unused
  `[backup]` section is removed.

### Changed (work package C1) - breaking

- Run the control plane and the runner in one process: `cursus serve --config` replaces
  `cursus control` and `cursus runner`. The runner reaches control through an in-process
  transport; the HTTPS pull transport, runner HTTP routes, bearer and digest, pairing
  metadata and cross-host settings (`service.origin`, `bearer_file`, `runner.tailnet_node`)
  are removed.
- Single configuration `schema_version = 3`, `process_kind = "serve"`
  (`deploy/cursus.example.toml`); `capacity` is required; the `long_poll_seconds` and
  `runner_spool_bytes` limits are removed. `cursus serve` refuses to run as root or as a
  user other than `service.user`.
- The runner/control protocol and runner journal are unchanged in meaning, so crash
  recovery semantics are retained. Control's specific error codes now reach the runner.
- Remove the two-process systemd units and templates; a single unit comes with the installer.

### Removed (work package C0)

- Remove the 0.6.0 installer stack, which built container images and paired two hosts:
  `deploy/install.py`, `native_setup.py`, `setup.py`, `setup-*.sh`, `deploy/native/*`,
  `deploy/runner.example.toml`, `cursus.containers`, `config.container_settings`,
  `config.capability` and their tests. `install.sh` now only explains that the installer is
  being rebuilt and changes nothing. README and ops documents are marked obsolete.

### Changed (work package B)

- Replace generated capability profiles with in-source CLI recipes (`cursus.recipes`):
  argv, prompt transport, read-only and clean-config flags are built from the role.
  Remove the capability file and digest, `profile_digest`, `qualified_roles`,
  `qualification` and the binary digest pin. `roles.toml` is `schema_version = 2`.
- Add `cursus preflight --roles roles.toml [--config runner.toml]`: checks that each
  CLI the roles use is installed and advertises every option its recipe emits, using
  version and help queries only. It does not check sign-in. A missing CLI fails a job
  with `cli_missing`.
- Claude's recipe adds `--no-session-persistence`, so runs do not fill the signed-in
  user's session history.
- Role `model`, `reasoning` and `provider` must be plain identifiers.
- Verified against Claude Code 2.1.330 help only; codex, agy and pi recipes are
  unverified against real installs.

### Changed (work package A)

- Run CLIs and verifier checks directly on the host as the service user through
  `HostRuntime`: allowlisted environment (`PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`,
  per-attempt `TMPDIR`, plus configured `pass_env`), worktree working directory,
  own process group, durable process ledger and identity-checked group termination
  after restarts. No isolation (ADR 0016).
- New runner `[execution]` configuration (`deploy/runner.host.example.toml`)
  replaces `[containers]`; credential domains, image pin and credential-concurrency
  enforcement are gone. Workspaces are always self-contained clones.
- Journal record kinds `container_*` are now `execution_*`; no migration of old journals.
- Fix: a command that exits before reading stdin no longer raises
  `ConnectionResetError` from the execution layer.

### Decided

- Run the operator's already-installed and already-signed-in Claude Code, Codex
  CLI, Antigravity and pi directly on one host in one process. Remove the native
  image, containers, credential domains, pairing and generated capability profile.
  Isolation is deliberately dropped; repositories must be trusted (ADR 0016,
  with a work-package plan). Supersedes ADRs 0011, 0014 and 0015 and most of 0009.


## [0.6.0] - 2026-11-20

Source update; no intended-host/provider qualification or release tag implied.

### Native install and login

- End fresh worker installation after the native image and persistent domain
  directories are installed. Save choices in `runner.pending.toml` and remind
  the operator to log into all four CLIs manually. Do not launch login/model
  selection, run authenticated checks, generate pairing or activate a service
  from that pending record. Reuse pending choices on rerun (ADR 0015).

- Separate Antigravity’s compressed-download bound (256 MiB) from its expanded
  executable bound (512 MiB): the official 1.5.13 executable exceeds 256 MiB.
  Retain SHA-512 verification and regular-file checks, report invalid entry size
  explicitly, and copy/hash binaries in chunks rather than reading them whole.

- Install Claude Code, Codex CLI, Antigravity and pi from their native distributions
  in the supplied execution-image recipe; pin the built image and record versions.
- Open those same installations for native login, preserve their isolated state
  in place, and generate capability metadata from budgeted installed-interface and
  login-persistence checks. Remove the user-authored measured-profile prerequisite.
- Refresh a clean default installer checkout on rerun; preserve dirty/diverged
  work and use a separate checkout so an old helper cannot restore the old prompt.
- Pair the controller using generated non-secret metadata; no native credentials
  are transferred. Distinguish native checks from full M3 acceptance (ADR 0011).
- Start Antigravity's private keyring inside its container and mask executable
  project customizations in generated native sessions. Support its actual native
  result envelope in addition to previously supported fixtures.


### Setup

- Use configured worker/provider ceilings as fixed session limits; remove
  admission reservations of each container’s maximum resource allowance. Keep
  aggregate cgroup protection, verifier separation and actual host memory/disk
  pressure checks. Generate shared agents-pool defaults rather than a 50/50
  per-agent/verifier split (ADR 0014). Existing individual limits are preserved.
- Run native onboarding, recovery and probe subprocesses from the runner-owned
  setup directory instead of inheriting an inaccessible operator home.

- Separate fresh installation from repository enrollment: save empty enrollment
  on both hosts, omit repository/branch/check/token questions, and preserve
  explicitly enrolled configurations. Explain later enrollment and show an idle
  state on the new-run screen (ADR 0013).
- Replace ambiguous resource prompts with purpose-specific questions, explained
  hardware-based suggestions accepted with Enter, immediate numeric/range
  validation and a summary of session ceilings with a separate verifier pool.
  Ask host reserves first and derive subsequent suggestions from chosen values.

- Explain guided inputs in plain English, including units, sources and account permissions.
- Import saved native model/provider choices without ID transcription.
- Discover Tailscale peers/accounts and worker hardware locally; select deployment
  roles by number, carry the worker DNS name in pairing metadata, and reject a
  pairing code addressed to another controller (ADR 0012).

- Add one top-level `install.sh` for both hosts, with fresh-checkout bootstrap,
  terminal-safe guided setup, optional automatic hash-locked wheel acquisition,
  private configuration/credential preparation and guarded stage/activation.
- Prepare required storage and the rootless user manager automatically; start
  local PostgreSQL before provisioning. Preserve existing work and secret files.
- Pin guided role/prompt configuration in separate local Git releases (ADR 0010).
- Lead README with quick install and move the manual path behind it; remove the
  scripted path’s assumption that `~/cursus-source` already exists.

### Documentation

- Replace the short README with a host-by-host Ubuntu deployment guide covering
  scripted and manual installation, prerequisites, native image/auth/profile
  qualification, private configuration, readiness, first task, upgrades, rollback
  and troubleshooting. Identify missing qualified vendor artifacts explicitly.

## [0.5.0] - 2026-11-20

Container execution replacement from clean main; rejected PR #6 was not merged.
Live qualification remains deferred to M3 end. No host provisioning or inference.

- Replace host execution identities with rootless Podman containers per session
  or verifier; retain the same debug container/RPC process across turns. Record
  intent/token and immutable runtime identity before launch; inspect/stop actual
  containers, preserve uncertain reservations and retry cleanup independently.
- Require explicit worker 1–4 and independent Claude/Codex/Antigravity 1–2 ceilings
  on both hosts. Reserve verifier resources in admission and separate cgroup
  slices; reconsider pending claims and rotate lane polling for progress.
- Keep native CLIs and qualified image/transport/tool profiles. Persist explicit
  disjoint native-auth domains in place, with exclusive leases and required
  concurrency/refresh qualification; no rotating-login copies or guessed paths.
- Keep publisher/cache authority outside container mounts; use self-contained
  Git metadata read-only inside production workspaces, with runner-owned capture.
- Add schema-2 deployment templates, both Ubuntu setup scripts, immutable
  source/config releases, drain/status contracts and explicit activation/rollback
  boundaries. No sixteen-account provisioning or parallel host backend.
- Expose lifecycle state/reasons/age and cleanup backlog. Compact retired journal
  history, bound replay, retry acknowledged workspace deletion, aggregate usage
  in SQL and reserve database connections from long waits. Supervise background
  tasks and contain malformed session output.
- Add migration 003 for independent provider lanes, ADR 0009 and a findings-to-
  acceptance matrix. Fixture evidence remains distinct from runtime/host/provider
  qualification; published Git/image retention beyond reserve checks stays WP-19.

## [0.4.0] - 2026-11-20

Source implementation through WP-16. User qualification and live testing are
deferred to the end of M3 (WP-17); no milestone acceptance or tag.

### Added

- WP-15: bounded immutable artifact upload, claim-scoped input retrieval,
  authorized attachment downloads and durable verifier evidence logs. Upload
  intent/receipt replay gates final delivery; metadata conflicts fail closed.
- WP-16: server-rendered accepted design, private Serve identity/CSRF/origin
  checks, durable forms, committed SSE replay/reset, real PR/evidence handoff,
  local pinned htmx, persistent light/dark/OS themes and accessible log controls.
- Add event retention watermark migration 002 and committed browser projections.
- ADR 0007 records M3 artifact/browser decisions and the operator's accepted
  design and qualification deferral until the end of M3.

## [0.3.0] - 2026-11-19

Public-source M2 implementation. User qualification and live testing are deferred
until further notice; no M2 tag or acceptance claim.

### Added

- WP-09: live M1 qualification procedure, per-boundary evidence checklist and
  explicit operator-input gates. Qualification remains unrun; no M1 tag.
- WP-10: validated package DAGs and independent delivery groups; parallel runner
  tasks, per-package candidate/evidence state, serialized integration and dependent
  dispatch from committed heads. Conflicting patches park safely; target drift triggers bounded merge, fresh
  verification and review before publication.
- ADR 0005 records the implementation scope and explicit live qualification deferral.
- WP-11: original-attempt commands, cancel/unknown/abandon guards, lost-grant and
  lost-ack replay, boot-change stop evidence, bounded interrupted retries and
  read-only publication reconciliation. Includes reachability projection without timeout-based ownership release.
- WP-12: continuing pi RPC debug turns, immutable checkpoint refs, separate
  verifier claims, durable continue/finish commands and exact passing-checkpoint
  review/PR handoff. Local tests execute a failing then passing check in one
  process and confirm cancellation. Concurrent workers lease distinct configured
  identities; the second identity requires its own measured profile.
- WP-14: prepared real phase/recovery/debug/debate acceptance procedures and
  private evidence fields. User qualification and live testing remain deferred;
  no VPS/provider calls or M2 tag.
- WP-13: revision-bound guided interviews, required-answer admission, fixed
  three-frontier-seat debate, immutable per-seat transcripts, validated author
  amendments, spec-question round trips and the three-round unresolved-blocker
  cap. Direct intake and bounded scout behavior remain available.


## [0.2.0] - 2026-11-19

Public-source M1 implementation; live M0/M1 qualification is pending. No release
tag or production-readiness claim is implied.

### Added

- WP-08: wired single-package planning, production, pinned verification,
  independent review, staged phase checks, durable intents and confirmed PR
  handoff. Invalid/missing evidence and target drift park before publication;
  negative verdicts consume at most two fresh repair attempts.

- WP-07: direct pinned CLI execution with explicit child environments, RPC/JSONL
  framing, bounded process groups, real verifier evidence and strict review.

- WP-06: runner-owned Git worktrees, pinned blob reads, exact candidate/stage
  refs, conditional integration updates and conservative exact PR lookup.

- WP-05: generation-scoped runner reconciliation, claims and event sequence
  ingestion, authenticated transport, exclusive hash-chained fsynced journal.

- WP-04: strict startup settings, pinned role/prompt release, private operator
  socket, durable code intake/status and offline-discoverable CLI commands.

- WP-03: PostgreSQL migrations, ordered transactions, atomic idempotency and
  committed reads/wakeups; disposable-database integration checks.

- WP-02: public control/runner provisioning examples, an explicitly unqualified
  capability worksheet, host/identity/tailnet procedures and a qualification log.
- ADR 0002 keeps private deployment inventory and live evidence operator-local.
  Live M0 provisioning/authentication checks and the release tag remain deferred.

## [0.1.0] - 2026-11-19

### Added

- WP-01: installable Python 3.12+ baseline with offline help/version, strict
  contract primitives, canonical JSON and request digests, and disposable tests.
- Hash-locked prescribed dependencies and build tools with permissive license
  evidence; ADR 0001 records the package and contract boundary.

This package version is a bootstrap baseline. It is not a qualified M0 release.
