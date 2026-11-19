# Qualification evidence

Revision: 2026-11-19-r1. Normative baseline: D1 v0.1.1, D2 v0.1.2,
implementation roadmap v0.1.1. Status describes evidence, not file existence.
Private deployment inventory and credentials do not belong in this public repo.

## WP-01 — local package acceptance: passed

- Date: 2026-11-19; source: commit `defdc95` (WP-01).
- Environment: Linux x86_64, CPython 3.14.4, isolated `.venv`, pip 25.1.1.
- Dependency lock: 21 pinned runtime/transitive/build distributions; downloaded
  bytes checked against release SHA-256 hashes. Complete bundled license review
  and artifact hashes: [dependency-licenses.md](../docs/dependency-licenses.md).
- Clean hash-locked install from an external disposable wheelhouse passed:
  `python -m pip install --no-index --find-links /tmp/cursus-deps --require-hashes -r requirements.lock`.
- Standard isolated build passed with the preverified wheelhouse and network
  disabled: `PIP_NO_INDEX=1 PIP_FIND_LINKS=/tmp/cursus-deps python -m build --wheel`.
  Output: `dist/cursus-0.1.0-py3-none-any.whl`. The non-isolated offline build also passed.
- `python -m pip install --no-deps --force-reinstall dist/cursus-*.whl` passed.
- `cursus --help` and `cursus --version` passed without services or credentials;
  help exposes only help/version. Isolated Python module invocation also passed.
- `python -m unittest discover -s tests/unit -p 'test_bootstrap.py'`: 13 passed.
- `python -m unittest discover -s tests/unit`: 13 passed.
- `python -m pip check`: no broken requirements.
- Assertions cover strict scalar bounds, duplicate keys including nested/escaped
  keys, UTF-8 and non-finite numbers, input/action/candidate variants, safe file
  names and repository paths, Git ref conformance, canonical digest equivalence,
  and isolated/cleaned empty workspaces. These are unit tests, not live model calls.
- Not verified: CPython 3.12/3.13, other architectures, deployment hosts or native
  provider/CLI credentials. M0 is not qualified by these local results alone.

## WP-02 — public repository artifacts: implemented

Delivered `deploy/control.example.toml`, `deploy/runner.example.toml`,
`deploy/capabilities.example.toml` and the [runbook](../ops/runbook.md).
The templates parse as TOML; cross-template root, identity and capacity conventions
are checked locally. No runtime config-validation claim is made: the loader is
WP-04 and capability-profile consumption is WP-07. Profiles have no qualified
roles or argv. These are provisioning instructions, not observed host controls.

The operator clarified this is public-repository work, so no private access
inventory, SSH operation, installation, login, tailnet change or inference was
requested/performed as part of this delivery. [ADR 0002](../docs/decisions/0002-public-provisioning-boundary.md)
records the boundary. Live acceptance below remains pending operator deployment.

## WP-02 — live M0 acceptance: not run

Store actual inventory, literal commands and sanitized evidence in the private
operator-local record described in the runbook. Mark an item passed only after
observing it on the intended host/device. A public attestation can refer to that
record without exposing names, addresses, account identifiers or credential paths.

| Gate | Required evidence | Result |
| --- | --- | --- |
| VPS-A inventory | Intended host role, CPython 3.12+, Git, systemd, approved CLI builds, isolated users/homes/roots and writable storage | Not run |
| VPS-B inventory | Intended host role, CPython 3.12+, PostgreSQL 16+, dedicated local DB role, artifact and backup roots | Not run |
| A tailnet | Literal `tailscale status`, expected peers and authenticated private connectivity | Not run |
| B tailnet/DB | Literal `tailscale status` and `pg_isready`, intended local DB auth confirmed separately | Not run |
| MyPC | Device-client pairing and private peer reachability, exact diagnostic/action and UTC time | Not run |
| Chromebook | Device-client pairing and private peer reachability, exact diagnostic/action and UTC time | Not run |
| pi native auth | Assigned user, approved OpenCode Go/model tuple, minimal headless success and renewal record | Not run |
| Claude native auth | Assigned user, pinned binary/model, minimal headless success and renewal record | Not run |
| Codex native auth | Assigned user, pinned binary/model, minimal headless success and renewal record | Not run |
| Antigravity native auth | Assigned user, pinned binary/model, minimal headless success and renewal record | Not run |
| No public ingress | Listener/firewall/forwarding/Funnel observations; no public app/DB route; no M0 browser route | Not run |
| Release gate | Exact commit/wheel digest, all preceding live evidence, reviewed release changelog and annotated SemVer tag | Deferred; no tag |

### Private per-CLI measurement form

Complete one record per required CLI, plus each additional enabled slot/reviewer
identity before use. No complete literal invocation can be recorded honestly
until the operator selects the installed build and native identity.

| Field | Operator-local value |
| --- | --- |
| Record ID, UTC time, host role, package commit | Pending |
| CLI, absolute binary, version, binary SHA-256 | Pending |
| Effective UID/GID, home, supplementary groups | Pending |
| Provider/subscription class, model, reasoning tuple | Pending |
| Native enrollment method, lifetime, renewal procedure and observed renewal | Pending; no secrets |
| Exact full argv (including headless/model/read-only/config-isolation flags), cwd, stdin/prompt transport | Pending installed-version measurement |
| Child environment variable **names** and allowed non-secret settings | Pending; never a full environment dump |
| Maximum invocations/concurrency/time, operator cost ceiling, vendor retry knowledge, stop mechanism | Pending; runbook defaults need operator cost authorization |
| Exit code, terminal success event, final sanitized response, elapsed time | Pending |
| Failure classification/stop evidence, if any; evidence reference | Pending |

Required invocation families are pi JSON/RPC, Claude print/stream-json,
Codex exec/JSON and Antigravity print/stream-json (D2 §4.1). A family name is not
an executed command. Never record a guessed flag or a fixture response as a
successful provider result. M0 checks authentication; full tool/permission and
wire-format qualification is a separate M1 gate.

## Predecessor handoff

WP-01 local acceptance is established. WP-02 public-source deliverables are
complete; live provisioning acceptance is deferred. WP-03 must confirm real
WP-02 acceptance and an empty authorized PostgreSQL instance before its runtime
verification. No fixture, branch, commit or tag can substitute for those checks.

## WP-03 — local storage verification

2026-11-19: PostgreSQL 18.6, CPython 3.14.4, disposable local database;
`test_store.py`: 3 tests passed. Assertions cover twelve concurrent ordered
commits, digest-equal request replay, changed-payload rejection, rollback with
no cursor gap, migration replay/digest mismatch and notification/cursor wakeup.
Live WP-02 prerequisite remains deferred (ADR 0003); this is local evidence only.

## WP-04 — local intake verification

2026-11-19: `test_intake.py`: 1 test passed using a real private Unix HTTP
socket and migrated PostgreSQL. Submission/replay produce one phase/job;
changed-key content, unsupported debate and unauthenticated ingress leave state
unchanged. Combined integration suite: 4 passed. Browser routes remain disabled.
Role files deliberately require installed-version qualification before deployment.

## WP-05 — local runner transport verification

2026-11-19: `test_runner_transport.py`: 1 test passed over real HTTP/Unix
transport with runner bearer and generation guards. Empty queue is idle;
operator intake supplies the sole claimed job; identical request UUID returns
one claim; durable journal reopens the grant; a sequence gap cannot advance ack.
Unit regression: 13 passed; integration regression: 5 passed. Full recovery and
process stop proof are not supplied by this transport-only check.

## WP-06 — local Git/publication boundary verification

2026-11-19: `test_repository.py`: 2 passed. Real bare remote and worktrees
exercise pinned blob read, candidate capture, staged integration, immutable
snapshot, conditional ref replay/mismatch and target refusal. REST fixture
checks exact PR identity, repeat lookup and closed-PR refusal. No real GitHub
permission or credential claim follows from these tests.

## WP-07 — local execution verification

2026-11-19: `test_execution.py`: 3 tests passed. Four actual executable fixtures
exercise pi RPC ID/terminal framing, Codex JSONL and Claude/agy final result
shapes; a parent-only sentinel is absent from children. A real failing verifier
command produces failed evidence at its supplied candidate. Invalid role/tier,
incomplete review and absent assistant output cannot pass. These same-UID local
fixtures do not prove cross-user, native-auth, vendor tools or systemd isolation.

## WP-08 — local connected single-package path

2026-11-19: the production CLI submits through a private HTTP Unix socket to
migrated PostgreSQL; a runner connects through authenticated HTTP, journals real
grants, invokes executable CLI boundaries, captures actual Git changes, executes
repository checks, reviews and publishes against the controlled GitHub seam.
No Cursus claims/candidates/evidence/intents are seeded by tests.

`test_one_package.py`: 6 tests. Inline and pinned repo sources confirm one PR at
the exact staged/reviewed head and leave target unchanged. Malformed review,
missing report, exhausted repair budget and target drift cannot publish. Event
replay uses process-produced spool records. `test_runner_transport.py` also
checks digest-equal event replay and conflicting repeated sequence rejection.

The final source regression and wheel results are recorded below after the
final verification run. Full crash/reconnect, cross-user/service controls,
provider behavior and real GitHub permissions remain separate qualification.

### Final local verification — 2026-11-19

- Installed version: 0.2.0; CPython 3.14.4/Linux, PostgreSQL 18.6.
- Unit discovery: **18 passed**; integration discovery: **17 passed**, no skips.
  Integration run: approximately 57 seconds, disposable random PostgreSQL
  schemas, private Unix HTTP sockets, local bare Git and executable CLI fixtures.
- The control composition smoke starts a separate production bootstrap process,
  reapplies migrations, submits via the actual operator socket, and confirms
  SIGTERM stops both listeners and removes its socket.
- Offline isolated wheel build from the preverified WP-01 wheelhouse passed;
  non-isolated build, wheel reinstall, offline submit help/version, migration
  inclusion inspection, compileall, `pip check` and `git diff --check` passed.
- Tested wheel SHA-256:
  `76a6978f2315823077b6c82b6a95714c9fac275786555927693bcc86922556db`.
  The isolated build reproduced the same wheel bytes.
- No model/provider, real GitHub, SSH, Tailscale or systemd deployment calls.
  Tests use same-UID executable boundaries; OS isolation remains unqualified.
