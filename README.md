# Cursus

Cursus coordinates coding agents on one machine. You describe a change; Cursus has an agent plan it,
another implement it, runs your repository's own checks against the result, has a different agent review
it, and gives you a GitHub pull request through a private website. **You do the merge.**

It does not bring its own agents. It runs the **Claude Code, Codex CLI, Antigravity and pi** installations
you already have, signed in as you, directly on your machine.

> **There is no isolation.** The agents and your repository's check commands run as your user, with your
> real home directory, files, credentials and network. Anything that can write code in an enrolled
> repository can read what you can read. Enroll **trusted repositories only**.

## Prerequisites

- Linux with systemd user services, Python 3.12+, `git`, and PostgreSQL 16+ (server running; the `psql` client
  installed). The installer creates the database role and database for you, using `sudo` for that step only.
- Tailscale, signed in, with MagicDNS and HTTPS enabled. The website listens on loopback only and trusts the
  identity headers from Tailscale Serve, so that is how you reach it. The installer reads your node name and
  login from `tailscale status`; it does not install, configure or sign in to Tailscale. Without Tailscale, pass
  `--origin` and `--operator-login` yourself.
- Each CLI your roles use is **installed and signed in as the user who runs Cursus**. Cursus never installs,
  updates, authenticates or inspects them and cannot tell whether one is signed in: a signed-out CLI fails on
  first use. Preflight (website: Settings, System) checks only that each is installed and supports the options
  Cursus needs.

## Install

Run as **your own user, not root**, from a checkout:

```bash
git clone https://github.com/playa77/cursus.git
cd cursus
./install.sh --dry-run     # shows the plan and the address it derived; changes nothing
./install.sh --yes         # does it all
```

The installer builds a hash-checked Python environment, creates private directories, commits and pins the role
release, writes a complete configuration (every value derived from this machine), creates the PostgreSQL role and
database, installs the user service unit, enables lingering, **starts Cursus** and waits until it answers. It then
prints the address to open. It never overwrites a value you set, never restarts a running service (so an upgrade
cannot interrupt work), and never signs in to a CLI. Rerunning is safe and is how you upgrade
([ADR 0017](docs/decisions/0017-per-user-installation.md), [ADR 0018](docs/decisions/0018-self-configuring-install-and-complete-gui.md)).
Use `--wheelhouse DIR` to install offline, `--no-start` to install without starting.

If something cannot be determined or done, the installer stops with a plain explanation and the exact next step.

## Set up on the website

Open the address the installer printed. The overview lists what is left, and the Settings pages let you do all of it
in the browser:

1. **Sign in** to each CLI your roles use, as your own user (the one thing no tool can do for you).
2. **Roles**: choose each role's model and reasoning level. Runs are refused until this is done.
3. **When you want pull requests**: set the GitHub token (Settings, Publisher) and enroll a repository with the
   commands that check its work (Settings, Repositories). With none enrolled Cursus is valid and idle.
4. **Restart** from Settings, System to apply saved settings (everything except the token takes effect on restart;
   the page tells you what is pending). Restart is refused while work is running unless you tick the box to
   interrupt it.

Cursus opens pull requests from its own branches. **You do the merge.**

## What the website covers

| Area | What you can do |
| --- | --- |
| Overview, Attempts | State of every phase and attempt; setup checklist; drain or reopen intake |
| New run | Code or debug; phase, one-shot or ticket; specification inline, from a pinned repository file, or by guided interview; optional specification and plan debates |
| A phase | Stepper; packages and their evidence; the specification, interview transcript, debate turns, plan and review findings; answer interview questions; steer a running pi session; cancel; downloads; the pull request; every committed event, live |
| An attempt | Its result and inputs; steer; declare unrecoverable; abandon |
| Settings | Access (origin, login, port), capacity, resources and CLI locations, limits, publisher and token, repositories and their checks, roles (CLI, model, reasoning, tools, timeout) and prompts |
| System | Version and state, drain, CLI check, restart, configuration history and restore |

Every save is validated by the same loader the service uses before it replaces the file, and the previous file is
kept (last 50). Role and prompt changes are committed to the role release repository and pinned, so a change to
authority is always a visible commit. Not editable, by design: the service user, loopback binding, the operator
socket, state and storage locations, the runner id, and the single verifier and repository lanes; Settings shows
them with the reason.

## Terminal client

Everything above also works from a terminal. Submit a run:

```json
{
  "workflow": "code",
  "form": "one-shot",
  "source": {"kind": "inline", "text": "Add a short explanation of the test command to README.md. Change no code. Acceptance: existing tests pass."},
  "repo": {"owner": "YOUR_OWNER", "name": "YOUR_ENROLLED_REPO", "target_ref": "refs/heads/main"},
  "plan_debate": false,
  "spec_debate": false
}
```

```bash
CURSUS=~/.local/share/cursus/venv/bin/cursus
KEY=$(python3 -c 'import uuid; print(uuid.uuid4())')   # keep it: retrying with it never submits twice
$CURSUS submit --input task.json --idempotency-key "$KEY"
$CURSUS status --phase-id ENTITY_ID_FROM_THE_REPLY
```

Start with a small change in an expendable repository: a run calls your CLI subscriptions or providers and writes
GitHub refs. The commands use `$XDG_RUNTIME_DIR/cursus/operator.sock`; pass `--socket` if yours differs.

## Operate

Logs: `journalctl --user -u cursus -n 80`. Stop, start, status: `systemctl --user stop|start|status cursus`.
Stopping ends the whole process group, including any CLI still running; on the next start Cursus stops
anything it can positively identify from the old run and reports the interrupted attempts. A stop cannot
resume an in-flight session.

Upgrading, backups, rollback and recovery from stuck attempts are in the [runbook](ops/runbook.md).
For how the pieces fit together, read the [architecture](docs/architecture.md).

## Troubleshooting

| Symptom | Likely cause and action |
| --- | --- |
| Installer: "Cursus is reached through your Tailscale network" | Tailscale is missing, stopped, or has no MagicDNS/HTTPS. Fix it, or pass `--origin` and `--operator-login`. Nothing was changed. |
| Installer: the role and database could not be created | The server is not running, or your user may not `sudo -u postgres`. The message lists the two commands to run by hand. |
| Installer: could not reach your user service manager | You are in a plain `su`/`sudo` shell. Log in normally and rerun; everything else is already in place. |
| The website is unreachable | Tailscale is not publishing it. Run `tailscale serve --bg 8787` (the installer prints it when it is missing). |
| Website 403 | The Tailscale login, host or origin differs from Settings, Access. If a wrong value locks you out, copy a file from `~/.local/state/cursus/backups/config/` over `~/.config/cursus/cursus.toml` and restart. |
| "Roles without a chosen model" when submitting | Settings, Roles: every role needs a model and reasoning level (and a provider for pi roles). |
| `identity_boundary` on start | Run as the non-root user named in `service.user`, not root or another user. |
| Role/prompt differs from the pinned release | Roles or prompts were edited on disk. Settings, Roles, "Commit and pin current files". |
| `cli_missing` on a job | That CLI is not on the search path. Settings, Resources, then Settings, System, "Run check". |
| A job fails on its first run with an auth error | The CLI is not signed in as this user. Sign in; Cursus cannot do it. |
| Database connection refused | Check the DSN file and that your user has a PostgreSQL role and the `cursus` database (rerun the installer). |
| `Failed to connect to bus` | No systemd user session; log in normally, or enable lingering, then rerun the installer. |

## Develop

Tests use local executable fixtures, not real providers. Unit tests need only the locked environment:

```bash
python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.lock
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/unit
```

Integration tests need a **disposable PostgreSQL** you are allowed to write to (they create and drop their own
schemas; never use production): `export CURSUS_TEST_DSN='postgresql:///cursus_test?host=/var/run/postgresql'`
then `... -m unittest discover -s tests/integration`. A missing DSN is an error, not a skipped test.

## Project documents

- [Architecture](docs/architecture.md), [runbook](ops/runbook.md), [changelog](CHANGELOG.md).
- [Architecture decisions](docs/decisions/), starting with
  [ADR 0016](docs/decisions/0016-host-native-single-host.md) (host-native design),
  [ADR 0017](docs/decisions/0017-per-user-installation.md) and
  [ADR 0018](docs/decisions/0018-self-configuring-install-and-complete-gui.md) (installation and the website).
- Original [design](docs/cursus-design-document-v0.1.1.md), [specification](docs/cursus-technical-specification-v0.1.2.md)
  and [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md), partly superseded (see the notice at the top of each).
- [Dependency licenses](docs/dependency-licenses.md), [MIT license](LICENSE).

Nothing here establishes live acceptance: the code has been exercised with fixtures and one installed Claude
Code, not on an intended host with real logins for all four CLIs. The installer's sudo/PostgreSQL provisioning,
systemd and Tailscale steps, and the website's restart cycle, have been tested only against simulated system calls.
