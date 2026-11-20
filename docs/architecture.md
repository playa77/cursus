# Cursus architecture (0.7.0)

This describes the system as built after [ADR 0016](decisions/0016-host-native-single-host.md). The original
[design](cursus-design-document-v0.1.1.md) and [specification](cursus-technical-specification-v0.1.2.md) remain
the source for the workflow, data and contract details they define; their notices list what is superseded.

## Shape

One host, one process, run as the signed-in user:

```
 browser ──(Tailscale Serve, loopback :port)──┐
 cursus submit/action/status ──(unix socket)──┤
                                              ▼
 ┌────────────────────────── cursus serve ──────────────────────────┐
 │  HTTP surfaces → Control ⇄ LocalTransport ⇄ Runner               │
 │                    │                          │                  │
 │                 Store (PostgreSQL)     Journal + HostRuntime     │
 │                 Artifacts (files)             │                  │
 └───────────────────────────────────────────────┼──────────────────┘
                                                 ▼
              claude / codex / agy / pi  (your installs, your logins)  and  git
```

`cursus serve` supervises three tasks: periodic maintenance, the HTTP surfaces and the runner. If any of them
ends, the process ends and the supervisor restarts it; the runner then reconciles from its journal and the
database.

## Components (`src/cursus/`)

| Module | Responsibility |
| --- | --- |
| `bootstrap` | CLI (`serve`, `preflight`, `submit`, `action`, `status`), identity check, supervision (`run`). |
| `config` | The single strict configuration loader, the pinned role release, enrollment and limits. |
| `control`, `store`, `transport` | The control plane: operator actions, queries, claims, events, in PostgreSQL transactions. |
| `workflows`, `scheduling`, `conversations`, `recovery` | The pure state machine, parallel packages with serialized delivery lanes, interview and debate seats, operator recovery. |
| `runner` | The durable journal and the runner loop; `LocalTransport` is its in-process path to control. |
| `host`, `execution`, `recipes` | Admission and process lifecycle, CLI protocols and output normalization, and the per-CLI invocation recipes. |
| `repository` | Git cache, self-contained workspaces, candidate capture, staging, publication and reconciliation. |
| `artifacts`, `artifact_control`, `artifact_http`, `http`, `browser` | Evidence files, and the operator socket and website surfaces. |

## Work and gates

A phase moves through intake, optional interview/debate, plan, execution, verification, review and delivery. A
worker produces a candidate in a self-contained clone with no remote. The verifier runs the repository's enrolled
check commands against that exact candidate and records observed exit codes and output as evidence. A separate
review session (by default a different CLI) reviews the candidate against the criteria and that evidence. Only then does Cursus stage and open a pull
request. Each gate checks identity (the candidate, the attempt, the digests), and every publication is an
intent that is reconciled before it can repeat. Cursus never merges.

## Roles and CLIs

`roles.toml` names, per role, the CLI, model, reasoning, tools, timeout and prompt. It and the prompts are pinned
to a git commit that startup verifies. `recipes.build` turns a role into the exact command for one of the four
supported CLIs; pi's mode follows the role's tools, and organization roles are restricted to read-only tools. A
model, reasoning or provider value must be a plain identifier. `cursus preflight` checks that the installed CLI
advertises every option a recipe can emit. Nothing installs, updates or signs in to a CLI.

## Execution and recovery

`HostRuntime` enforces the per-CLI concurrency ceilings and the memory and disk reserves, spawns each child with an
allowlisted environment in its own process group, and records the child's pid, start time and boot id in a durable
ledger before reading any output. Stopping a session signals the group only after the identity is confirmed, so a
reused pid is never killed. The runner journal and the control plane's database are reconciled at start with an
idempotent, sequence-checked protocol (claims keyed by request id, events with digests, held claims and
dispositions). That protocol is why a crash between a database commit and a journal write loses nothing and
launches nothing twice; it was kept deliberately when the runner moved in-process.

## Trust and limits

There is no sandbox. Children run as the user with the user's real home and network, so repositories must be
trusted. The only scrubbing is the allowlisted environment and a working directory inside the worktree. Project
customization directories are not masked; each CLI's own clean-configuration flags are the only control, and
that they hold on real installs is verified for Claude Code's options only.

## Not yet done

Live acceptance with real logins for all four CLIs; verification of the codex, agy and pi recipes against real
installs; a real systemd user session and PostgreSQL peer-authentication run of the installer; automated backups;
a revision of the original specification text.
