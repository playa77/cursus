# ADR 0016: Host-native runners on a single host

- Status: accepted direction; implementation pending; no host qualification
- Date: 2026-11-20
- Authority: operator instructions in this session: reorganize and simplify; every
  runner/worker used (Claude Code, Codex CLI, Antigravity, pi) must already be
  installed and signed in on the target machine, as a prerequisite for any
  installation; the CLIs run on the host as the signed-in user; the target is one
  host and one process; the isolation loss is accepted with a scrubbed environment;
  scope covers installer/setup, topology, and role/capability contracts.
- Supersedes (see "What is superseded"): [ADR 0009](0009-container-execution.md),
  [0011](0011-native-install-and-login.md), [0014](0014-shared-execution-resources.md),
  [0015](0015-manual-native-login.md); the pairing/discovery and resource-prompt
  parts of [0010](0010-unified-installer.md) and [0012](0012-discovered-installer-inputs.md).
- Retains: [ADR 0013](0013-idle-installation.md) (install without repository
  enrollment); exact candidate gates, independent review, publication recovery,
  immutable roles/prompts, drain/activation checks (ADR 0009's workflow-side
  invariants, restated below).
- Target release: 0.7.0 (breaking change to configuration, CLI surface and wire contracts).

## Context

Cursus 0.6.0 installs the four native CLIs itself inside a Podman image, isolates
each session in a container with leased per-domain credential directories, derives
a capability profile from authenticated native checks, and splits control and
execution across two Tailscale-paired hosts. Most of the installer and setup code
(`install.sh`, `deploy/install.py`, `deploy/native_setup.py`, `deploy/native/*`,
`src/cursus/containers.py`, and the profile/credential-domain validation in
`config.py`) exists to manufacture a trusted, logged-in CLI environment that the
operator already has. Installation also repeatedly failed at the login step
(ADR 0015). The operator wants that machinery removed.

## Decision

1. **Prerequisite, not installer work.** Each CLI a deployment uses must already be
   installed and signed in for the account that will run Cursus. Cursus never
   installs, updates, authenticates, selects models for, copies, or inspects the
   credentials of a CLI. The set of CLIs required is derived from the roles file,
   so a deployment using only `pi` and `claude` need not have `codex` or `agy`.
2. **Preflight without inference.** A read-only preflight resolves each required
   CLI to an absolute path, runs its version/help query, and compares the result
   to the recipe the source supports. It runs no inference and no login probe.
   Sign-in is the operator's responsibility; a signed-out or expired CLI surfaces
   as a native CLI failure on first use, reported with sanitized output. Cursus
   makes no claim that a CLI is signed in.
3. **Execution on the host as the signed-in user.** Native CLIs run directly as
   the service account's own user, with its real `HOME`, so they use their own
   login state in place. Each child process gets a minimal environment allowlist
   (`PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `TMPDIR`, plus only variables a
   specific CLI is documented to need for its own login store), a working directory
   inside the session worktree, its own process group, and the existing bounded
   output, timeout, group-termination and no-orphan checks. The service runs as the
   signed-in user, not a dedicated account.
4. **Verifier.** Repository check commands run the same way: same user, scrubbed
   environment, worktree working directory, no separate `HOME`. A disposable
   verifier `HOME` was considered and not selected.
5. **No isolation claim.** There are no containers, namespaces, cgroups, network
   restrictions or per-session credential domains. Trusted repositories remain
   mandatory. Agents and verifier checks can reach everything the user can,
   including `~/.ssh`, other CLIs' credentials and the network. Documentation and
   installer output must say this plainly and must not describe the setup as
   sandboxed. An opt-in sandbox (for example bubblewrap) is a possible later,
   separate decision.
6. **Concurrency.** The worker (1–4) and claude/codex/agy (1–2 each) ceilings and
   the single verifier and repository lanes remain explicit concurrency limits.
   Admission keeps the existing actual-pressure guards (available memory above a
   reserve, free disk above a floor); per-session cgroup limits are removed.
   Concurrent sessions of one CLI now share one login and its token refresh;
   provider-side behavior of that is unqualified and no silent lowering of
   ceilings is introduced.
7. **One host, one process.** Control and execution run in a single `cursus` service.
   Remove the pairing code, bearer and its digest files, Tailscale peer discovery,
   the runner HTTPS pull transport and cross-host heartbeat/reconnect logic.
   Recovery semantics are retained as constraints (no double launch, no lost
   candidate, no duplicate publication, interrupted attempts reported and not
   silently restarted); whether the runner journal survives in some form is decided
   in work package C against those constraints, not assumed.
8. **Roles and capability contracts.** Remove the generated capability profile and
   everything bound to it: capability file/digest, `qualification` state, image pin,
   `credential_concurrency`, `REPLACE_*` placeholders and the `profile_digest`
   binding. `roles.toml` stays the one operator-authored file (cli, model,
   reasoning, tools, timeout, prompt). The per-CLI invocation recipe (fixed
   arguments, prompt transport, read-only flags, clean-configuration flags, output
   normalization) moves into versioned source code with tests, selected by the
   preflight version check. Immutable role/prompt release pinning is retained;
   its content-addressed pin no longer depends on a capability digest.
9. **Installer.** Reduce to: verify prerequisites and preflight; install the
   hash-locked Python packages; prepare PostgreSQL access and private
   configuration; install and start one service unit. Delete the image recipe,
   native tool installer, private keyring helper, native setup, pairing, Tailscale
   discovery and resource-prompt code. Questions still read from `/dev/tty`;
   dry-run/help still make no changes; existing config and credentials are never
   overwritten (ADR 0010, 0013 behavior retained).

## What is superseded

- ADR 0009: Podman runtime, image, per-session containers, credential-domain
  leases, cgroup slices, dedicated runner account. Its workflow-side invariants
  remain (exact gates, independent review with immutable input, publication
  recovery, trusted repositories, drain before upgrade).
- ADR 0011: native install in an image, installer-driven login, generated
  `native-checked` profile, keyring, customization masks.
- ADR 0014: shared cgroup pools, verifier slice, resource prompts. Ceilings and
  pressure guards survive as described above.
- ADR 0015: pending-login record and "log in later" reminder. Its principle that
  the installer never drives authentication is adopted and generalized.
- ADR 0010/0012: two-host selection, Tailscale discovery, pairing metadata.

## Consequences

- A large amount of code, config schema and documentation is deleted. This is a
  breaking change: runner and control configuration schemas change and the
  capability file disappears. The prior 0.6.0 deployment shape was never
  qualified on an intended host; no migration of existing deployments is planned
  (assumption to confirm).
- The security posture is weaker than 0.6.0 by operator choice: untrusted code in a
  repository can read the user's credentials. This is accepted, documented, and
  limited to trusted repositories.
- Project-local executable customizations (`.claude/`, `.codex/`, `.agents/`, ...)
  are no longer masked by tmpfs overlays. Decided in WP-A: the only control is
  each profile's `clean_config_argv`, applied on every invocation; no mask is
  reintroduced. Whether those flags suppress project customizations on real
  installed CLIs, and whether they leave the user's login intact, is unverified
  and is checked in WP-B against real installs.
- Read-only roles (review, scout, planning) previously had a read-only mount.
  On the host they rely on the CLI's read-only flags, which `Execution.authorize`
  already requires; the workspace is not made unwritable.
- The CLI binary digest pin is dropped: an operator-installed CLI may update itself.
  Only the presence of an absolute, executable path is checked.
- Compatibility is checked by advertised options, not version ranges: the preflight
  requires every long option a recipe can emit to appear in the installed CLI's help.
  The version string is reported for information only.
- Because host sessions write to the signed-in user's real configuration directory,
  Claude's recipe adds `--no-session-persistence` so Cursus runs do not accumulate in
  the user's own session history. Claude's `--safe-mode` (verified in its 2.1.330 help)
  also disables CLAUDE.md; this is accepted.
- Model, reasoning and provider values reach argv, so they must be plain identifiers
  (no leading `-`, spaces or shell characters), checked when roles load and again when
  an invocation is built.
- Antigravity's login store may need `DBUS_SESSION_BUS_ADDRESS`/`XDG_RUNTIME_DIR`
  from the user's session; the allowlist and service unit must be verified on a
  real host. No such verification has been done.
- The normative design and technical specification documents describe the old
  topology and contracts and need a revision (work package D).

## Open questions

1. How is the operator's browser access exposed on one host? Today the installer
   arranges Tailscale Serve identity; this ADR removes installer-managed discovery
   but not the loopback listener, Unix socket or `external_origin` setting.
2. PostgreSQL stays as the store. Replacing it is outside this ADR.
3. Confirm that no 0.6.0 deployment needs an upgrade path.

## Acceptance

Defined per work package in
[the plan](../superpowers/plans/2026-11-20-host-native-single-host.md). No result
from fixtures, version queries or local tests may be reported as a successful
real login, provider call, or intended-host qualification.
