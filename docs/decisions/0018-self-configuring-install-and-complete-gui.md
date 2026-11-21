# ADR 0018: Self-configuring installer and a complete operator GUI

- Status: accepted; implemented in 0.8.0 with fixtures only. The real-host steps (sudo PostgreSQL
  provisioning, `loginctl enable-linger`, `systemctl --user enable --now`, Tailscale detection against a real
  tailnet, restart under systemd) are unverified.
- Date: 2026-11-21
- Authority: operator instruction in this session. The operator rejected (a) the 0.7.0 post-install checklist,
  (b) the "installer refuses to do the PostgreSQL step because it needs sudo" constraint, and (c) a GUI that
  only submits and watches runs. They asked for an installer that finishes the job and a GUI that exposes the
  complete logic and every operator-modifiable setting of the application.
- Supersedes: [ADR 0017](0017-per-user-installation.md) items 5, 7 and 9 (and the "Alternatives rejected" entries
  on prompting, provisioning PostgreSQL and auto-filling policy values). Items 1-4, 6, 8 and 10 stand, except
  that the installer may now start and enable the service.
- Amends: [ADR 0016](0016-host-native-single-host.md) item 8 consequence "an unqualified role refuses to load":
  an unqualified role no longer prevents the service from starting; it prevents submitting work.
- Retains: ADR 0013 (idle is valid), ADR 0016 (host-native, no isolation, immutable pinned role release).

## Context

0.7.0 reduced installation to "put files down, then follow a seven-step checklist", and the website only submits
and watches runs. Everything that determines behavior (roles, models, capacity, reserves, limits, repositories,
checks, credentials, origin, login) lives in two files that the operator hand-edits and a git pin they copy by
hand, followed by a manual restart. The checklist existed because the installer had been scoped to "never
configure", not because the work needs a human. Most of the values can be derived from the machine; the rest
belong in a GUI that can validate them.

## Decision

### Installer

1. **The installer completes the installation.** It derives every value the machine can answer, then verifies
   the result: package environment, private directories, role release (committed and **pinned automatically**),
   complete `cursus.toml`, database role and database, DSN file, user unit, `loginctl enable-linger`,
   `systemctl --user enable --now cursus`, and a readiness check against the operator socket. A failed step
   stops with a prose explanation of the cause and the exact next action; files already written are kept and a
   rerun continues.
2. **Derived values.** User, group, runtime directory, paths and runner id as before. New: `execution.path`
   (the installing user's own absolute, existing `PATH` entries followed by the system defaults, so the CLIs
   resolve as they do in the shell), default `pass_env` (`XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`),
   `capacity` (worker 2, claude/codex/agy 1), `disk_reserve_mb` (10% of the state filesystem, bounded 512-5120)
   and `host_reserve_mb` (10% of memory, bounded 512-4096), and `role_release_commit`. These are conservative
   defaults, not policy claims; every one is editable in the GUI.
3. **Access identity comes from Tailscale or from flags.** The installer reads `tailscale status --json` for the
   node's DNS name (`external_origin`) and the signed-in user's login (`operator_login`). It does not install,
   log in to or configure Tailscale, and it does not run `tailscale serve`. If Tailscale is absent, stopped or
   the node is tagged (no user), it stops before changing anything with an explanation; `--origin` and
   `--operator-login` supply the values explicitly. If a Serve entry for the listen port is not visible it
   prints the command to publish it, as a notice, not an error.
4. **PostgreSQL.** Check whether `postgresql:///cursus` already works. If not, create the database role and
   database: directly when the user may, otherwise through `sudo -u postgres psql`, which prompts for the
   password itself on a terminal. This is the only use of `sudo`; the installer still refuses to run as root
   because the service must run as the user that owns the CLI logins (ADR 0016 item 3). It never installs
   PostgreSQL. Identifiers are validated before being quoted into SQL.
5. **Existing installations are completed, not overwritten.** An existing `cursus.toml` keeps every value; only
   remaining `REPLACE_*` values for which a derivation exists are filled in (the previous file is kept as a
   timestamped backup). An existing roles repository keeps its history; uncommitted role/prompt edits are
   committed with a message that says the installer did it, and the resulting commit is pinned.
   A running service is **not** restarted on upgrade (that would interrupt work); the installer says so.
6. **Not derivable, therefore left to the operator and the GUI:** signing in to each CLI (undetectable by design,
   ADR 0015/0016), the model/reasoning/provider of each role (policy), the GitHub token, and repository
   enrollment. The GUI's setup checklist lists exactly these.

### GUI

7. **The website is the complete operator surface.** Anything the operator can do through the operator contract
   or the configuration is available in the browser: submit, answer, steer, cancel, declare unrecoverable,
   abandon, **drain/reopen**, deployment state, preflight of the CLIs, and a Settings area covering every
   operator-policy key: access identity and port, capacity, execution resources/paths/CLI locations/environment
   pass-through, limits, publisher (credential files and a write-only token), repositories with their checks,
   roles and prompts, and configuration history with restore.
8. **Not exposed, with reasons:** `service.user` (must equal the running user), `listen_host` (loopback is an
   invariant), `operator_socket`, `dsn_file`, the state/artifact/repository/worktree/review roots and
   `runner.id` (changing them orphans existing state), `roles_file`/`prompts_root` (derived from the release
   repository), `schema_version`/`process_kind`, and the verifier/repository lanes (fixed at one by ADR 0016).
   They are shown read-only.
9. **Configuration is managed by Cursus, hand edits remain valid.** Saves rewrite `cursus.toml` from the parsed
   document (comments in the file are not preserved; the shipped example documents the keys). A save is
   validated by the **real loader** against a candidate file in the same directory before an atomic replace,
   and the previous file is kept in `state/backups/config/` first. The operator may still edit the file by
   hand and restart.
10. **Settings take effect on restart.** The process builds its runtime (capacity, repository enrollment,
    resources, roles) at startup; hot-applying subsets would create partially applied states. Each page shows
    whether the file on disk differs from what is running and which sections differ. The restart action ends the
    process with exit status 75; the unit's `Restart=on-failure` brings it back. It is offered only when
    supervised by systemd (`INVOCATION_ID` present), and **refuses while attempts are active or work is queued**
    unless the operator explicitly accepts interrupting them (ADR runbook: a restart cannot resume a CLI session).
11. **Roles are still an immutable, visibly committed release.** Saving a role or prompt validates it with the
    same rules as startup, commits it to the roles repository (message names the operator and the changed roles)
    and updates `role_release_commit`, all in one operation. Pinning still means "startup refuses files that
    differ from the commit", so a change to authority is always a commit; the GUI just stops making the operator
    run git by hand.
12. **Unqualified roles do not block startup; they block submission.** A role whose model, reasoning or provider
    still holds a `REPLACE_*` value is loaded with `qualified = false`. Submitting work is refused with a problem
    naming the roles and the page that fixes them. This lets a fresh install start, serve the GUI and be
    completed there.

## Open question: conversation with the system

The website exposes every interaction the backend has: the structured interview (agent asks, operator answers),
steering a running pi session, and read-only views of the debate. It does **not** have a freeform conversation
about project status or proposed changes, because no such workflow exists in the backend or in the original design
documents. Adding one is a new feature with its own decisions: a new role, a context assembler (phases, plans,
evidence, repository state), persisted conversations, a path from an agreed change to a real run, a read-only
boundary, and a live-inference cost cap. Repository text entering an agent's context is a prompt-injection surface.
It is proposed as WP-E5 (see the plan) and **deferred by the operator until further notice** (2026-11-21); no code,
route or navigation entry for it exists.

## Alternatives rejected

- Keep the checklist and improve the README: the operator rejected it; most steps are derivable.
- Hot reload: partial application of capacity, enrollment and role changes, with the recovery implications for
  in-flight attempts, is a larger and riskier change than a gated restart. Revisit with evidence.
- Auto-selecting model names: cannot be verified against a provider here; a wrong default is worse than a clearly
  incomplete role. The GUI blocks submission until the operator chooses.
- Running `tailscale serve` from the installer or the GUI: the operator declared Tailscale setup out of scope.
- Editing `cursus.toml` in place with a comment-preserving library: a new dependency for little value.

## Consequences

- **Security.** Settings writes are privileged: a repository check's argv runs as the user, a token is written to
  disk, and `operator_login` decides who may reach the site. This is the same authority class the operator already
  has by submitting a run to agents that have `bash`; the same Serve-identity, Host, Origin and CSRF checks guard it,
  with no new network surface. Secrets are write-only (never rendered or echoed, never placed in events or logs).
  A wrong `operator_login`/`external_origin` locks the operator out of the site; the validated-save and the
  automatic backup limit the risk, and a backup can be restored by hand (`cp`) and the service restarted.
- The README, runbook and architecture documents are rewritten around "install, open the website".
- `cursus.toml` loses hand-written comments after the first GUI save.
- Version 0.8.0 (new feature set; one behavior change: unqualified roles no longer stop startup).

## Verification

Offline unit and integration tests run the real installer logic in a temporary home with the system calls
(pip, systemctl, loginctl, sudo, tailscale, psql) recorded and simulated, and the real loader, real PostgreSQL
schema and real HTTP surface for the GUI. Not verified: any real sudo/PostgreSQL provisioning, systemd user
session, linger, tailnet or CLI login, and the restart cycle under systemd.
