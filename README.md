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

- Linux with systemd user services, Python 3.12+, `git`, and PostgreSQL 16+ reachable by your user over
  its local socket.
- Each CLI your roles use is **installed and signed in as the user who runs Cursus**. Cursus never
  installs, updates, authenticates or inspects them, and cannot tell whether one is signed in: a
  signed-out CLI fails on first use. `cursus preflight` checks only that each is installed and supports
  the options Cursus needs.
- To publish pull requests (only when you enroll a repository): a GitHub token and a git credential file,
  both private (mode 0600).
- To reach the website: it listens on loopback only and trusts the Tailscale Serve identity headers, so
  publish it over HTTPS with Tailscale Serve (see Tailscale's documentation).

## Install

Run as **your own user, not root**, from a checkout:

```bash
git clone https://github.com/playa77/cursus.git
cd cursus
./install.sh --dry-run     # shows the plan and changes nothing
./install.sh --yes         # applies it
```

The installer builds a hash-checked Python environment, creates private directories, a role release repo,
a starting config, a database DSN file and a user service unit. It never overwrites an existing file,
never starts anything and never signs in to a CLI. Rerunning it is safe and is how you upgrade
([ADR 0017](docs/decisions/0017-per-user-installation.md)). Use `--wheelhouse DIR` to install offline.

## Configure

The installer ends with a numbered checklist; these are the steps. Paths below are the defaults.

1. **Sign in** to each CLI your roles use.
2. **Create the database once:**
   `sudo -u postgres createuser "$USER" && sudo -u postgres createdb -O "$USER" cursus`
3. **Qualify the roles.** Edit `~/.config/cursus/roles/roles.toml` (model, reasoning and, for pi, provider
   per role), then commit it in that repository:
   `git -C ~/.config/cursus/roles commit -am "Qualified roles"` and read the hash with
   `git -C ~/.config/cursus/roles rev-parse HEAD`. Cursus refuses to start if the roles or prompts differ
   from the commit you pin, so a change to authority is always a visible commit.
4. **Edit `~/.config/cursus/cursus.toml`.** Fill every `REPLACE_` value; loading names any that remain.
   The choices are yours: `capacity` (concurrent sessions per CLI), `execution` reserves (new sessions wait
   while free disk or memory is below them), `service.role_release_commit`, `external_origin` and
   `operator_login` (your exact Tailscale login). Set `[execution] path` to the directories that hold your
   CLIs: a service starts with a minimal `PATH`.
5. **Check your installs:**
   `~/.local/share/cursus/venv/bin/cursus preflight --roles ~/.config/cursus/roles/roles.toml --config ~/.config/cursus/cursus.toml`
6. **Run once in the foreground** to validate everything, then stop it with Ctrl-C:
   `~/.local/share/cursus/venv/bin/cursus serve --config ~/.config/cursus/cursus.toml`
7. **Run it as a service:** `loginctl enable-linger "$USER" && systemctl --user enable --now cursus`

With no repository enrolled Cursus is valid and idle. To enroll one, uncomment and fill the
`[[repositories]]` block in the config (a literal check command, run as you from the candidate's worktree)
and restart. Cursus opens pull requests from its own branches; it never merges.

## Use it

Open the private HTTPS address in your browser, or submit from a terminal. Save this as `task.json`:

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

Start with a small change in an expendable repository: a run calls your CLI subscriptions or providers and
writes GitHub refs. The commands use `$XDG_RUNTIME_DIR/cursus/operator.sock`; pass `--socket` if yours differs.

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
| `Replace every REPLACE_ placeholder` | The message lists each unfilled value in `cursus.toml`. |
| `identity_boundary` on start | Run as the non-root user named in `service.user`, not root or another user. |
| Role/prompt differs from the pinned release | You edited roles or prompts without committing and re-pinning `role_release_commit`. |
| `cli_missing` on a job | That CLI is not on `[execution] path` (or `[execution.clis]`). Run `cursus preflight`. |
| A job fails on its first run with an auth error | The CLI is not signed in as this user. Sign in; Cursus cannot do it. |
| Database connection refused | Check the DSN file and that your user has a PostgreSQL role and the `cursus` database. |
| Website 403 | The Tailscale login, host or origin differs from `operator_login` / `external_origin`. |
| `Failed to connect to bus` after install | No systemd user session; enable lingering or log in normally, then `systemctl --user daemon-reload`. |

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
  [ADR 0016](docs/decisions/0016-host-native-single-host.md) (this design) and
  [ADR 0017](docs/decisions/0017-per-user-installation.md) (installation).
- Original [design](docs/cursus-design-document-v0.1.1.md), [specification](docs/cursus-technical-specification-v0.1.2.md)
  and [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md), partly superseded (see the notice at the top of each).
- [Dependency licenses](docs/dependency-licenses.md), [MIT license](LICENSE).

Nothing here establishes live acceptance: the code has been exercised with fixtures and one installed Claude
Code, not on an intended host with real logins for all four CLIs.
