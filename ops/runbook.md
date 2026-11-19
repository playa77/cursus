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
