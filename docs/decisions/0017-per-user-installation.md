# ADR 0017: Per-user installation, no provisioning

- Status: accepted; the real-host steps (systemd user session, PostgreSQL role, CLI logins) are unverified
- Date: 2026-11-20
- Authority: operator instruction to reorganize and simplify; [ADR 0016](0016-host-native-single-host.md)
  item 9 (reduce the installer to prerequisites, packages, private configuration and one unit).
- Supersedes: [ADR 0010](0010-unified-installer.md) (the unified two-host installer and its piped
  `curl | bash` entry). Retains [ADR 0013](0013-idle-installation.md): a fresh install is valid with no
  repository enrolled.

## Context

The 0.6.0 installer needed root, built container images, discovered Tailscale peers, paired two hosts,
generated capability profiles and asked about resources. ADR 0016 removed all of those reasons to exist.
What remains is small: put the code somewhere, create private directories, give the operator a correct
starting configuration, and install one service unit.

## Decision

1. **Run as the signed-in user; refuse root.** Cursus uses that user's own CLI logins, so installing as
   anyone else would defeat the premise. No `sudo`, no system packages, no PostgreSQL provisioning.
2. **Run from a checkout** (`./install.sh`), not through a pipe. No automatic clone, no network fetch of
   source. The installer does not choose a release for the operator.
3. **Layout, all under the user's home and private (0700):** `~/.local/share/cursus/venv`,
   `~/.config/cursus/{cursus.toml, database-dsn, roles/}`, `~/.local/state/cursus/*`, and a user unit
   `~/.config/systemd/user/cursus.service`.
4. **Packages:** a venv from `requirements.lock` with `--require-hashes` (offline from `--wheelhouse` when
   given), then the checkout installed with `--no-deps --no-build-isolation`. A rerun refreshes the package.
5. **Configuration:** written from `deploy/cursus.example.toml` with only mechanical values filled (user,
   group, paths, runner id). Capacity, reserves, origin, login, role release commit and repositories stay
   as `REPLACE_*` for the operator to choose; loading names every unfilled value. Nothing is defaulted on
   the operator's behalf (ADR 0013 for repositories: none enrolled is a valid idle state).
6. **Roles** are scaffolded as a separate git repository at `~/.config/cursus/roles` holding the unedited
   files, so the operator qualifies and commits their own release without dirtying the source checkout.
7. **Database:** the installer writes a DSN file for local peer authentication (`postgresql:///cursus`),
   which holds no secret, and prints the two commands that create the role and database. It does not run them.
8. **Never overwrite** an existing config, DSN, roles repository or unit. A differing unit is written beside
   it as `cursus.service.new`.
9. **Never start, enable or sign in.** The installer ends with an ordered checklist; enabling the service
   and `loginctl enable-linger` are the operator's actions. `--dry-run` changes nothing; changes need
   `--yes` or an interactive confirmation.
10. **The unit** uses `KillMode=control-group` so that stopping the service ends orphaned CLI descendants.

## Alternatives rejected

- Prompting for every setting (as 0.6.0 did): large, hard to test, and inventing answers is worse than
  naming the blanks.
- Provisioning PostgreSQL or installing system packages: needs root and widens the installer's authority
  for little benefit; the operator already administers the machine.
- A system-wide service under a dedicated account: contradicts running as the signed-in user.
- Auto-filling model names or capacity: these are operator policy and cost decisions.

## Consequences and verification

Upgrade is `git pull && ./install.sh --yes` then restarting the service after draining. Offline tests run
the real installer logic in a temporary home with pip and venv stubbed, including a check that the
installer's output plus the documented operator edits loads through the real configuration loader. The
real venv, hash-locked install and package build were also run once in a scratch home. Not verified: a
systemd user session, enabling linger, PostgreSQL peer authentication, and any real CLI login.
