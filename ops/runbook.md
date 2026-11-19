# Cursus operations runbook

Revision: 2026-11-19-r1. Scope: WP-01 package and WP-02 provisioning.

## Deployment status and records

M0 supplies offline package discovery only. There is no control/runner service,
DB schema, operator socket or browser route yet. Do not run future `control`,
`runner`, `submit`, `status`, `action` or maintenance commands as M0 checks.
[Qualification](../tests/qualification.md) distinguishes local results from live
gates. [ADR 0002](../docs/decisions/0002-public-provisioning-boundary.md) records
the public/private boundary.

Keep the actual inventory and qualification log in an operator-managed private
location outside this checkout, for example `/var/lib/cursus-qualification`
(mode 0700, administered by the operator). Record UTC times, release commit,
host roles, versions, commands, exit codes and sanitized outcomes there. Never
record token values, DSNs, credential file contents or complete environments.
Only a non-sensitive attestation reference and gate disposition need be public.

## Install the package

Use CPython 3.12+ in an isolated virtual environment. Build on an admin host or
CI, with Git available for unit ref checks. PostgreSQL 16+ is required on VPS-B
for later packages, not to display bootstrap help. See the root
[README](../README.md#bootstrap-wp-01) for hash-locked install/build/test commands.
Copy the same wheel and lock to each deployment environment and install there;
record its SHA-256 and release commit. Preserve bundled dependency licenses.
No model SDK, Node frontend toolchain or CLI wrapper is part of Cursus.

## Host inventory and native tools

Complete the private inventory before provisioning. Record actual DNS/tailnet
addresses, authorized administrative access method, OS/architecture, service
users/groups, roots, software versions and storage availability. Example paths
are conventions for new deployments; reconcile existing installations before
creating or changing anything. Do not apply blanket ownership changes.

| Host | Required runtime/tools | Role |
| --- | --- | --- |
| VPS-A | CPython 3.12+, Git, systemd, Tailscale, pi/claude/codex/agy and required build tools | One runner; all model CLI work, worktrees and verification |
| VPS-B | CPython 3.12+, PostgreSQL 16+ server/client tools, systemd, Tailscale; Hermes for WP-19 | Sole control process and DB client, immutable artifacts, later private Serve ingress |
| MyPC | Existing browser and approved Tailscale client | Operator client; no v1 runner |
| Chromebook | Existing browser and approved Tailscale client | Operator client |

Use approved OS/vendor distribution procedures for pinned host-tool builds.
Before installing a CLI, review its installed-version documentation and approved
source/package integrity; record installer source, version and binary digest.
Do not pipe unreviewed network scripts into a shell. Do not install optional CLI
extensions, MCP servers or project-discovered tooling to clear an auth probe.
The package environment does not install or authenticate host tools.

## Accounts and isolated directories

These names match `deploy/*.example.toml`; they are proposed deployment identities,
not assertions that accounts exist. Give each unprivileged user a private home
(mode 0700) with no supplementary group granting access to other identities.
Provision native provider login separately under each designated user. Do not
copy the developer agent's credentials or another user's native credential store.

| Host | Identity | Home/root and ownership |
| --- | --- | --- |
| B | `cursus-control` | `/var/lib/cursus-control` and `artifacts`, 0700, control-owned |
| B | `cursus-operators` group | Future `/run/cursus/operator.sock`, only authorized local operators |
| A | Trusted runner parent (`root`) | `/etc/cursus/runner`, `state`, `spool`, `repositories`, root-owned 0700 |
| A | `cursus-pi-1`, `cursus-pi-2` | `/var/lib/cursus-identities/pi-1`, `pi-2`, each owned by its worker |
| A | `cursus-verifier` | `/var/lib/cursus-identities/verifier`, verifier-owned |
| A | `cursus-claude` | `/var/lib/cursus-identities/claude`, Claude-owned |
| A | `cursus-codex` | `/var/lib/cursus-identities/codex`, Codex-owned; default reviewer |
| A | `cursus-agy` | `/var/lib/cursus-identities/agy`, Antigravity-owned |
| A | Optional `cursus-pi-reviewer` | `/var/lib/cursus-identities/pi-reviewer`, separate read-only reviewer |

The runner-owned top-level `/var/lib/cursus-runner` and workspace/review parents
need traversal (e.g. 0711); keep state/spool/credentials separately inaccessible.
Later runner code creates per-attempt writable worker directories and immutable
read-only reviewer snapshots, with access only for the assigned identity.
Do not give all workers a shared writable parent. Agent/verifier exec must drop
UID/GID and supplementary groups; no repo code executes as the trusted parent.
Actual boundary probes are M1 checks, not proven by this directory plan.

Install release files root-owned under `/opt/cursus/release` and the isolated
package environment at `/opt/cursus/venv`. Neither worker nor verifier may edit
these. On B reserve `/etc/cursus/control` (0700 control-owned, secret files 0600)
for the local DSN and runner bearer digest. On A reserve `/etc/cursus/runner`
(root-owned 0700, secret files 0600) for the bearer and publisher credentials.
Keep native CLI auth in the designated identity's supported native location;
Cursus consumes it opaquely. A private home name is not proof of isolation.

## Configure the private deployment

Copy [control](../deploy/control.example.toml), [runner](../deploy/runner.example.toml)
and [capabilities](../deploy/capabilities.example.toml) to operator-managed paths
outside the checkout. Replace every `REPLACE_*` marker, keep runner ID/origin,
identity homes and binary paths consistent, and verify owners/modes. Do not put
secrets into TOML; secret-path fields refer to separately provisioned local files.
Generate the runner bearer via an approved secret-management procedure and
transfer only its SHA-256 digest to B. Only B receives a local DB DSN.

Keep control on `127.0.0.1`; PostgreSQL accepts only intended local control/admin
connections. Create a dedicated local database role/database for Cursus and
record PostgreSQL version, auth policy, DB ownership and storage reserve. Use
peer auth or an operator-provisioned secret opaquely; never pass passwords in
argv or source. Do not weaken host auth to make a readiness test pass.

Enroll only trusted, operator-authorized GitHub repos. Replace the example
verification command with an actual approved literal argv, relative cwd,
timeout and phase check IDs for that repo. Pin allowed targets and object format;
verify GitHub automation cannot merge or push targets on Cursus publication.
Publisher credentials stay under the trusted runner parent. They authorize only
enrolled work/integration refs and PR operations; final merge remains operator-owned.
Actual GitHub permission probes belong to M1, not M0 authentication checks.

The capability file is an unqualified worksheet: empty argv/role arrays and
`unqualified` signatures are deliberate. Do not invent a binary digest, model
flag, permission switch or success signature. Fill it from actual installed
versions and immutable probe evidence; hash the finalized bytes and set the
runner's `capabilities_digest`. Any CLI update invalidates affected qualification.
No config loader or role activation exists at M0.

## Tailnet and no public ingress

Enroll all four intended machines through the operator's approved Tailscale
workflow. Verify ACL/grant rules allow only intended operator clients and the
runner to the future private service. Do not enable Funnel, public app listeners,
public PostgreSQL, public reverse proxies or browser routes during M0.
On A and B record `tailscale status`; on B also record `pg_isready` (or the
recorded local socket/DB parameters), `python3 --version`, `psql --version`, and
`sudo ss -lntup`. `pg_isready` success is readiness, not proof of authenticated DB
permissions; confirm the intended local role with an approved opaque client.

From MyPC and Chromebook record successful authenticated tailnet connectivity
to the intended peers using the platform-supported client diagnostic. Record
the exact command/UI action, destination, UTC time and result privately. No
Cursus browser page is expected yet. Confirm host/provider firewalls and tailnet
policy: no public Cursus/DB listener, no public forwarding or Funnel. Public SSH
administration, if already authorized, is separate from Cursus app ingress.

[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) is the later
private HTTPS boundary. Its identity-header behavior must be measured at M1;
M3 enables browser routes only after those checks. Do not start Serve against a
nonexistent backend merely to make an M0 record look complete.

## Native CLI login, renewal and bounded M0 probes

Authenticate the four CLIs under their actual configured users, using their
supported native enrollment flows. Keep operator interaction for initial login
separate from the subsequent non-interactive smoke. Record account/subscription
class without secrets, binary path/version/digest, effective UID/GID/home,
authentication method, known lifetime (or explicitly unknown), documented renewal
procedure and last successful renewal. The second pi slot requires its own
native provisioning before use; optional pi review remains disabled until qualified.

Consult installed-version help and official references to select literal flags:
[pi RPC](https://upd.dev/badlogic/pi-mono/src/branch/argument-finalization/packages/coding-agent/docs/rpc.md),
[OpenCode Go](https://opencode.ai/docs/console/go#endpoints),
[Claude headless](https://code.claude.com/docs/en/headless),
[Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode), and
[Antigravity headless](https://antigravity.google/docs/cli/headless/).
D2 requires direct pi JSON/RPC, `claude -p --output-format stream-json`,
`codex exec --json`, and `agy -p --output-format stream-json`; these prefixes
are requirements to measure, not complete qualified invocations.

Before any live run, the operator records a cost ceiling and verifies the chosen
subscription/provider's billing behavior. No numeric spend authorization is
implied by this runbook. Default M0 batch budget: four CLI subprocess invocations
(one per CLI), one in flight, maximum 120 seconds each plus 10-second termination
grace, no automatic harness retries. Use an empty disposable directory and the
prompt `Reply with exactly CURSUS_M0_OK. Do not use tools.` Record unknown internal
vendor request/retry counts; a process bound is not a provider-side cap. Stop on
throttling/auth denial or a prompt for approval; no credential or identity rotation.

Launch the measured command with a supported supervisor that tracks only its own
child/process group and has a verified stop path. Example *launcher shape*, not
an executable probe until exact argv and paths are recorded:

```text
sudo -H -u DESIGNATED_USER -- env -i HOME=DESIGNATED_HOME PATH=APPROVED_PATH \
  /usr/bin/timeout --signal=TERM --kill-after=10s 120s ABSOLUTE_BINARY QUALIFIED_ARGV
```

Use an explicit child-environment allowlist with only needed non-secret runtime
settings (including operator-approved proxy/CA settings when needed). Native
clients may use their own operator-provisioned auth opaquely. Never inherit the
developer-agent API key or environment. Do not pass credentials via argv or log
raw client output that may contain secrets. Verify that termination actually
stopped task-owned children; record unknown outcomes rather than blindly retrying.

Record each *literal* minimal headless invocation, prompt transport, installed
version, model/provider/reasoning tuple, exit code, terminal success event and
sanitized final response in the private qualification log. An exit code alone
is insufficient. Four successful non-interactive responses and documented renewal
clear only M0 auth. They do not prove read-only tools, RPC steering, event
correlation, GitHub permissions or effective cross-user isolation; qualify those
in WP-07/09 using pinned profiles before enabling roles.

## M0 release gate

Complete the checklist in [qualification](../tests/qualification.md), including
both devices, directories and native CLI evidence. Link a sanitized attestation
if publishing a result. Tag only the exact reviewed commit whose evidence passes.
A local example parse or test fixture cannot clear a live gate. No M0 tag has
been created by this public-source implementation. Backup/restore procedures
and Hermes scheduling will be added and tested in WP-19.

## Disposable PostgreSQL integration checks (WP-03)

Set `CURSUS_TEST_DSN` only to an authorized disposable PostgreSQL 16+ database.
The test user needs CREATE SCHEMA; each test creates a random `cursus_test_*`
schema, migrates it and drops only that schema. Never point tests at production.
Run `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/integration`.
No credential files or developer-agent environment are used for model execution.
A missing DSN is a test setup error, not a silently skipped successful check.

## M1 control and local CLI

Deploy the reviewed wheel and committed `roles.toml`/`prompts` together. Pin the
role commit; startup compares prompt/role bytes to that revision. Replace all
model/provider placeholders with measured settings. Configure a private DSN and
runner bearer digest file (0600); control reads these only at startup.
`cursus control --config /etc/cursus/control.toml` migrates before listening.
The systemd template gives the operator group socket access. A pre-existing
socket is a startup failure: verify the previous service stopped before removing
its stale socket. Do not change permissions to clear a test.

`cursus submit --input /absolute/input.json [--idempotency-key UUID]` wraps Input
JSON in a submit action. `--socket PATH` selects the protected local socket.
Read `entity_id` from the reply as PHASE_ID; run
`cursus status --phase-id UUID`. Persist `request_id` for retries. `action` accepts
an Action JSON file; `-` reads stdin. All subcommand help is offline. M1 admits
only code with inline or pinned repo source and no debates/interviews. Unsupported
features fail closed. The runner listener cannot authorize operator actions.

## Runner-owned repositories (WP-06)

Enroll the same exact owner/repo/target on both hosts. Runner remote URLs are
computed GitHub HTTPS URLs; local fixture remotes are supplied only by tests.
Git commands disable system/global config, hooks, external diff and textconv;
publishing consumes only the separately provisioned credential-store file.
Never let worker/verifier users access the cache, state or publisher files.
Expected-head leases are additionally restricted to fast-forward ancestry; no
history replacement or target publication is authorized. PR creation has no
automatic retry after an uncertain request. Preserve the intent and reconcile.

## M1 execution and publication (WP-07–08)

The runner enrollment must mirror control enrollment. Its fixed GitHub HTTPS
remote is computed from owner/name. Configure native credentials separately;
never supply the developer agent's keys or environment. `roles.toml` pins the
SHA-256 of the exact qualified capabilities file as `profile_digest`. Runner
startup verifies that digest and the binary/user/home enrollment. Each launch
checks binary bytes, role/model/provider/reasoning, exact tool set, approved
prompt transport and clean-config/read-only arguments. Fill `fixed_argv` with
the **complete measured command**, including static model and tool flags.
The implementation recognizes only the documented terminal shapes in the
capability worksheet; a vendor format change requires source requalification.

A CLI profile may contain `[pi.role_profiles.scout]` or
`[pi.role_profiles.reviewer]` overrides for distinct measured argv, tools and
identity. A pi reviewer requires `pi_reviewer.enabled=true`, a separate user/home
and qualified read-only role profile. Never reuse worker write authority.
Default organizational roles use Claude and Codex. An initial planner scout
request has `kind=scout_request`, one `question`, and
`input_refs=["repository_snapshot"]`; a second scout request parks the plan.

M1 schedules one step at a time; declared capacities are upper bounds. Independent
10-second heartbeats continue while a CLI executes. Transport has at most two
in-flight exchanges (one long poll plus heartbeat); the external GitHub REST
boundary is serial with at least one second between calls. Runner transport
retries are limited to five failed cycles/120 seconds, with capped exponential
backoff and jitter; authorization failure stops intake. Provider-internal
retries remain unknown until measured. No Cursus inference retry/failover exists.

Production and verifier execution drop UID/GID and supplementary groups. The
explicit child environment contains HOME/USER/LOGNAME/PATH/LANG/TMPDIR only.
Process groups are bounded by role/check timeouts, terminated before capture,
and unresolved descendant termination parks ownership. The systemd cgroup is
the deployment backstop; prove its behavior in WP-09. Trusted Git administration
uses runner-owned metadata even if a worker changes its workspace `.git` file.
Review snapshots exclude Git metadata and reject links/special files; verifier
snapshots are writable only by the verifier. Parent paths must permit traversal
without exposing cache, state or credentials (see Accounts above).

Workflow progression requires a structured production report, exact immutable
candidate, complete successful command evidence and independent criterion review.
It verifies the separate staged tree and all enrolled phase checks before
committing publication intents. The current M1 path parks on target drift.
A negative criterion/verdict allows at most two fresh production attempts after
the initial attempt, each with a separate workspace/ref and fresh checks/review.
Missing/malformed output parks rather than guessing success. PR handoff includes
the exact head, repository, number and URL; Cursus has no merge operation.

Journal records are append-only, hash-chained and fsynced under an exclusive
lock. Preserve the state directory and generation. A torn trailing record can
be removed only when the earlier prefix is intact. Corrupt history, prior
unresolved launch intents or uncertain publication are not permission to rerun.
The spool cap preserves terminal-record reserve; persistence failure stops intake.
A known unlaunched grant can be recovered after reconciliation. Full cancellation,
abandonment and uncertain-outcome recovery are WP-11, not M1 operators' ad hoc
SQL procedures. Do not edit rows, delete journals or manually replay publisher
commands to clear a parked gate. Services report sanitized IDs/outcomes via
journald; model logs are sanitized before journal/event storage.

## WP-09 — live M1 qualification procedure

This section prepares qualification; it is not evidence that deployment or any
probe ran. Keep private machine/account values in the operator-local record.
Do not tag M1 until every gate in `tests/qualification.md` passes. Carry forward
M0 evidence and the exact source commit/wheel SHA-256. No new runtime feature is
introduced during this package.

1. Verify the intended hosts, private listeners, DB role, users, filesystem and
   systemd boundaries from WP-02. Install the same reviewed wheel/release on both
   hosts. Use the actual installed CLI versions to fill all qualified profiles,
   role tuples and literal argv. Measure native login/renewal per identity.
   Check binary digests and commit the non-secret role/prompt release before
   setting its revision. Keep credential paths/configuration operator-local.
2. Before each live probe record maximum launches/turns, one in-flight model
   process, timeout and termination grace, operator-approved cost ceiling and
   known/unknown vendor retry behavior. Use operator-provisioned native test
   credentials, never developer-agent keys. Use an explicit child environment.
   A timeout/process bound is not an enforced provider spend cap. Stop on auth
   denial, forbidden approval prompts or throttling; honor Retry-After and do
   not rotate identity. Record the exact task-owned stop mechanism and outcome.
3. Measure pi JSON and RPC, actual Go tool execution and final-report framing;
   in a dedicated bounded RPC probe exercise ID-correlated prompt, active steer,
   idle prompt and abort. Distinguish accepted steering from demonstrated
   consumption. Measure Claude, Codex and Antigravity independently, including
   a required legitimate read, attempted forbidden write/shell/MCP and terminal
   success/error. Record literal **installed-version** argv and sanitized wire
   fixtures. If a required signature differs, fix the supported parser/config
   and rerun affected tests; never declare a guessed flag qualified.
4. Probe cross-user file/process/credential access and systemd descendant stop.
   All workers, verifier and reviewer must lack publisher/cache/state/other-slot
   authority. Verify the verifier can run only its supplied literal check and
   the reviewer cannot modify the immutable candidate. Inspect actual listener,
   firewall, Serve and tailnet ACL state; no public app or DB ingress.
5. On both operator clients use a temporary operator-managed, loopback-only
   identity probe behind the intended private Serve origin. Record its exact
   invocation/configuration and safe boolean outcomes. Check the exact canonical
   Tailscale login, missing/wrong/duplicate identity and injected identity headers.
   An injected header must not impersonate the operator. Remove the temporary
   probe after observing its outcome; leave M1 browser routes disabled.
6. Enroll an explicitly authorized trusted test repo on both hosts. Confirm its
   GitHub automation cannot update/merge the target as a publication side effect.
   Set the approved literal phase check argv/cwd/timeout. Record target SHA and
   GitHub permission observations. Plan the live phase's maximum model launches,
   repair/scout allowance, concurrency, elapsed-time/cost ceilings and stop path
   before submission. These ceilings require operator input; none is inferred
   from public templates or subscription names.

Example Input JSON, after replacing repository and real-work text locally:

```json
{
  "workflow": "code",
  "form": "one-shot",
  "source": {"kind": "inline", "text": "REPLACE_WITH_AUTHORIZED_SMALL_CHANGE_AND_ACCEPTANCE_CRITERIA"},
  "repo": {"owner": "REPLACE_OWNER", "name": "REPLACE_REPO", "target_ref": "refs/heads/main"},
  "plan_debate": false,
  "spec_debate": false
}
```

On VPS-B inspect `systemctl status cursus-control`, then run
`cursus submit --help` and `cursus submit --input "$M1_INPUT"`, with M1_INPUT an
absolute file path. Copy reply `entity_id` to PHASE_ID and retain `request_id`.
Inspect VPS-A `systemctl status cursus-runner`; query
`cursus status --phase-id "$PHASE_ID"` at a bounded operator-selected interval
(at least 10 seconds for this qualification), stopping at delivered, parked or
the predeclared time budget. Record phase/attempt/publication IDs, check evidence,
creator/reviewer identities, exact PR head/base/URL and the independently observed
unchanged target. Do not seed state or manually push/PR to rescue acceptance.

Only after all gates pass, review the exact tested source and milestone changelog
and obtain scoped release-tag/publication authorization. A failed/missing probe,
unknown remote result or absent actual credential keeps M1 unqualified. Preserve
all existing claims and journals for the recovery package rather than deleting
state to rerun a qualification scenario.

## M2 recovery controls (WP-11)

A disconnect or missed heartbeat never releases a claim. Preserve the generation
and journal. Reconnect first reconciles held claims and replays contiguous events;
a known grant without launch intent can start once. A changed boot identity proves
that old processes stopped. Same-boot launches without terminal/process evidence
remain unknown; an absent PID alone is not proof. Do not delete journal files.

Submit operator actions through `cursus action --input PATH`. Use
`declare_unrecoverable` with attempt_id and a reason to park an uncertain attempt.
Only `abandon` on an already parked unknown can invalidate it and permit a bounded
replacement. First isolate any possible old execution. Delayed results from an
abandoned attempt are stale audit only. Publication intents require read-only
reconciliation; abandonment cannot waive uncertain remote effects. PR absence
after an ambiguous creation is insufficient proof to blindly create again.

`cancel` takes phase_id, cancels queued work and sends stop commands to held
attempts. A phase remains canceling until held execution and publication effects
resolve. `steer` takes the original active pi attempt_id and text. Commands are
journaled before dispatch and correlated by command ID; uncertain delivery is
never automatically injected again. Inspect command results in committed events.
