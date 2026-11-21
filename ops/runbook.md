# Cursus operations runbook

For the single-process, per-user deployment ([ADR 0016](../docs/decisions/0016-host-native-single-host.md),
[ADR 0017](../docs/decisions/0017-per-user-installation.md)). Installation and first configuration are in the
[README](../README.md). The commands below assume:

```bash
CURSUS=~/.local/share/cursus/venv/bin/cursus
CONFIG=~/.config/cursus/cursus.toml
```

There is no isolation: agents and checks run as your user. Do not run Cursus against untrusted repositories.

## Daily operation

| Task | Command |
| --- | --- |
| Status | `systemctl --user status cursus` |
| Recent logs | `journalctl --user -u cursus -n 80` |
| Stop / start | `systemctl --user stop cursus` / `systemctl --user start cursus` |
| Deployment state | `$CURSUS status --deployment` |
| One phase / attempt | `$CURSUS status --phase-id ID` / `--attempt-id ID` |
| Check your CLIs | `$CURSUS preflight --roles ~/.config/cursus/roles/roles.toml --config $CONFIG` |

The website covers all of this and more (Settings, System: drain or reopen intake, check the CLIs, restart,
configuration history and restore). From the terminal, the operator actions are available too (`$CURSUS action --input FILE`, a JSON file): `answer`, `steer`, `cancel`, `declare_unrecoverable`,
`abandon` and `set_drain`.

Stopping the service ends the whole process group. Cursus cannot reconnect to a running CLI session after a
restart: on start it stops anything it can positively identify from the earlier run (by process id and start
time, never by name), reports the interrupted attempts and lets the workflow retry or park. Do not use a
restart to continue an active debug session.

## Drain and upgrade

1. Stop new work and wait for the rest to finish. On the website: Settings, System, "Drain intake" (the page
   shows the unresolved attempts and queued jobs). From a terminal:

   ```bash
   printf '%s\n' '{"kind":"set_drain","enabled":true}' > "$HOME/cursus-drain.json"
   $CURSUS action --input "$HOME/cursus-drain.json"
   $CURSUS status --deployment     # wait for drain: true, unresolved_attempts: 0, queued_jobs: 0
   ```

   Drain stops new claims. If it strands queued work, reopen (`"enabled":false`), let it finish, drain again.
2. Stop the service and **back up** (below) before changing code or schema. The service applies database
   migrations forward on start; older code cannot read a newer schema.
3. Update the checkout and reinstall: `git pull && ./install.sh --yes`. Read the [changelog](../CHANGELOG.md)
   for config changes. If a differing unit was found the installer wrote `cursus.service.new` beside yours;
   compare, replace if appropriate, then `systemctl --user daemon-reload`.
   The installer does not restart a running service, so after it finishes the old code is still running: restart
   from Settings, System (or `systemctl --user restart cursus`) once work has drained.
4. Start the service, check `$CURSUS status --deployment`, and reopen intake (website or terminal):
   `{"kind":"set_drain","enabled":false}`. Intake stays drained across a restart until you reopen it.

## Settings changes and restarts

Settings saved on the website apply when Cursus restarts (the GitHub token applies immediately). The website
shows which settings are pending. Restart from Settings, System; it is refused while attempts are active unless you
tick the box to interrupt them, which is the same as `systemctl --user restart cursus` for those sessions: they are
not resumed. Every save keeps the file it replaced in `~/.local/state/cursus/backups/config/` (last 50). If a wrong
access setting locks you out of the website, restore one by hand and restart:

```bash
ls -t ~/.local/state/cursus/backups/config | head
cp ~/.local/state/cursus/backups/config/cursus-YYYYMMDDTHHMMSSffffffZ.toml ~/.config/cursus/cursus.toml
systemctl --user restart cursus
```

## Backups

Backup is manual; there is no scheduled or automated backup, and restore is not automated. With the service
stopped and work drained:

```bash
umask 077
pg_dump --format=custom --dbname=cursus --file="$HOME/cursus-$(date +%Y%m%dT%H%M%S).dump"
cp -a ~/.local/state/cursus/artifacts "$HOME/cursus-artifacts-$(date +%Y%m%dT%H%M%S)"
```

Keep the database dump and the artifact tree from the same moment, protect them as private data, copy them
off the machine, and verify a restore into an empty database and directory before relying on them.

## Rollback

Reinstall the previous commit (`git checkout PREVIOUS && ./install.sh --yes`) with its matching config. This
is safe only if the database schema is compatible: if the newer release applied a migration, restore the
backup taken before the upgrade, or stay on the new release and fix forward. Keep intake drained while you
decide.

## Recovery

- **Unknown attempt after a crash or disconnect.** The phase parks. Establish from the evidence whether the
  work happened, then use `declare_unrecoverable` and `abandon` (each with `attempt_id` and a `reason`) so the
  workflow can retry under a new attempt. Never resubmit under a fresh idempotency key just because a response
  was lost: the same key returns the original result.
- **Execution cleanup pending** (the browser shows the reason and age). Cursus could not confirm that an old
  process group has stopped, so it keeps that session's capacity reserved and retries every ten seconds. Look
  for the surviving processes yourself (`ps -o pid,pgid,lstart,cmd -u "$USER"`) and stop the ones you recognize
  as that run. Never delete the execution ledger or the journal under `~/.local/state/cursus/state`, and never
  kill every `node` or `python` process.
- **Storage pressure.** New sessions wait while free disk or memory is below the configured reserve; that is an
  admission check, not a quota. Workspace deletion is queued durably and retried.
- **Provider throttling or authentication denial.** Stop the affected workload and honor any cooldown. Do not
  rotate identities or loop retries. A GitHub denial pauses publication until you investigate and restart.

## Troubleshooting

See the table in the [README](../README.md#troubleshooting). Read the service journal first and record the
sanitized error code, time and commit; never paste secrets or complete configs into a report.

## Not implemented

Automated backups and restore, scheduled maintenance, a built-in way to expose the website, and any form of
sandboxing. Live acceptance with real logins for all four CLIs on an intended host has not been performed.
