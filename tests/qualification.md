# Qualification evidence

Revision: 2026-11-19-r2. Normative baseline: D1 v0.1.1, D2 v0.1.2,
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

- Runtime source: `663d64c` (WP-08); installed version: 0.2.0; CPython 3.14.4/Linux, PostgreSQL 18.6.
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

## WP-09 — live M1 qualification: blocked on operator inputs

Public-source procedure and evidence schema are prepared. **Acceptance is not
complete.** No VPS deployment, live model invocation, native credential access,
Serve change, real GitHub mutation or milestone tag was performed in this task.
ADR 0002's public/private boundary remains in effect. Required operator inputs
are the private M0 attestation, intended hosts/service identities, qualified
native test credentials and invocation measurements, an authorized real-work
repo/spec, and per-run cost/time/termination authorization.

| Gate | Required operator-local evidence | Status |
| --- | --- | --- |
| M0 predecessor | Actual WP-02 inventory, all four CLI auth/renewal outcomes, both clients and no-public-ingress evidence | Not supplied |
| Installed release | Source commit, wheel hash, Python/PostgreSQL/Git versions, committed role/prompts and measured profile digest on both hosts | Not run |
| pi JSON/RPC | Exact argv/tuple, Go tool call, terminal report, prompt/steer/abort correlation and consumption evidence | Not run |
| Claude | Headless read-only structured success/failure, forbidden tool/config tests and renewal | Not run |
| Codex | Headless read-only structured success/failure, clean project config and renewal | Not run |
| Antigravity | Native cached auth, headless stream success/failure, effective read-only tools and renewal | Not run |
| OS/service isolation | Distinct UID/GID/groups/homes, denied cross-slot/parent credential access, descendant stop with service/boot/process identities | Not run |
| Private ingress | Intended listeners/ACLs and both clients' canonical, absent/wrong/duplicate/forged Serve identity probe | Not run |
| GitHub authorization | Trusted repo, permitted owned refs, target/merge denial, safe repo automation | Not run |
| Real one-package trace | Actual CLI submit/status, durable phase/attempt/evidence/verdict/intents, one confirmed PR at exact verified head, unchanged target | Not run |
| M1 release | All prior gates passed at exact reviewed commit, scoped tag authorization, annotated SemVer tag | Deferred; no tag |

Use the private per-CLI form above for literal commands, probe outputs and budgets.
Record also each negative probe's expected denial and observed effect, rather
than accepting a success exit code as proof of effective tool restrictions.
The public workbook intentionally retains `qualification="unqualified"` and
empty role grants; fixture evidence must never populate live probe evidence.

## WP-10–13 — local M2 implementation

Source implementation adds graph/group scheduling, concurrent runner tasks,
serialized integration, recovery/commands, continuing RPC debugging, guided
interviews and distinct frontier debate seats. ADRs 0005/0006 record the durable
choices. Tests use empty PostgreSQL schemas, private Unix HTTP sockets, isolated
Git remotes and executable CLI/GitHub boundary fixtures. They call no live model,
provider, VPS, tailnet, or GitHub service.

Observed local results (2026-11-19, Linux x86_64, CPython 3.14.4,
PostgreSQL 18.6; final runtime source `435a87f`):

- Full integration regression: **38 passed** against the clean-installed M2
  wheel after the target-drift lane fix. An earlier run found the lane waiting
  behind its own owner; that defect was corrected, with all five scheduling
  scenarios also rechecked successfully.
- Final stale-process/verifier changes: affected recovery/debug suites,
  **12 passed**. After final subprocess lifecycle cleanup, execution **3 passed**
  and debug **5 passed**, including live-stale-process stop, cancellation,
  missing reproduction, turn cap and same-PID failing/passing checkpoints.
- Final clean-installed wheel: unit suite **18 passed**; offline CLI help/version
  and `pip check` passed. `compileall` and `git diff --check` passed.
- Offline isolated wheel build and clean hash-locked dependency installation
  passed using the existing verified wheelhouse. Final wheel:
  `dist/cursus-0.3.0-py3-none-any.whl`, SHA-256
  `7ea470a23f6dde9fd1aab6d499e8217903366400b41d73e52c47dca862dc5343`.
- Scheduling assertions cover distinct parallel claims/refs, plan order,
  dependent committed bases, independent delivery groups, serialized lane writes,
  actual runner-service dispatch and bounded target-drift revalidation.
- Recovery assertions cover lost grant and ack, control restart, ownership versus
  reachability, proven stop, explicit unknown/abandon, stale finals/verifiers,
  cancellation before launch and remote effects reconciled without duplicate PRs.
- Interview/debate assertions cover socket answers, required-input gating,
  revision changes, five fresh seat invocations with three distinct fixture CLI
  families, amendments, wrong-seat rejection and unresolved third-round parking.

These checks do not qualify deployment users, native credentials, real CLI tool
restrictions, cross-user/cgroup isolation or any A1–A4 live acceptance criterion.

## WP-14 — M2 qualification: explicitly deferred

Operator direction: **user qualification and live testing are deferred until
further notice**. This supersedes the roadmap's instruction to run live WP-14
now. The procedure/checklist is implemented; its live acceptance is not complete.
Do not submit real runs, change VPS services/networking, conduct provider probes
or create an M2 milestone tag under this implementation task.

When the operator resumes qualification, create four private absolute Input JSON
paths and retain the returned phase/request IDs. Never invent real-work inputs.
Record these fields for each scenario: tested source/wheel digest; role release
and capability digest; literal input path/command; approved repository and target
SHA; UTC start/end; attempt/job IDs; effective users and process/boot/service
identities; verifier/review evidence; publication intent/ref/head and PR URL;
intervention log; actual launch/turn/concurrency counts; cost observations and
unknown vendor retry behavior. Keep credentials and private inventory out of source.

| Scenario | Input requirements | Required observations | Result |
| --- | --- | --- | --- |
| M2 phase / A1, A3 | Authorized real code phase, at least five packages, independent ready packages and dependencies; exact approved checks | Two pi attempts overlap in different identities/worktrees/refs; dependents pin committed heads; serialized combined checks/review; exact reviewed PR; no operator interventions | Deferred |
| Recovery / A2 | Separate disposable trusted phase, bounded fault windows and cleanup | Control restart/link disconnect retain attempt; ordered replay once; proven stop uses fresh bounded attempt; unknown holds ownership; explicit abandon invalidates stale results; ambiguous mutation reconciles without duplicate effect | Deferred |
| Debug / A4 | Real reproducible failing project and fix criteria; one debug package | Same pi RPC process across multiple turns; independent failed then passing checkpoint evidence; exact passing SHA reviewed and delivered without final operator stop | Deferred |
| Debate / A7 | Plan or spec debate with pinned author and three distinct frontier CLIs | Fresh rationale/critic/reply/judge/amendment sessions, correct seat inputs, durable transcript, spec-answer revision if asked, accepted amendments or parked third round | Deferred |
| Capacity/isolation | Two qualified worker identities plus verifier/frontier/repository lanes | Actual load behavior, credential/filesystem/process isolation and cgroup cleanup on intended VPS-A | Deferred |
| Milestone | Every live gate above and applicable M0/M1 evidence | Reviewed exact source, sanitized attestations, scoped release authorization | No M2 tag |

Before each run, the operator supplies maximum process launches, debug/interview/
debate turns and repairs, allowed concurrency, elapsed-time and cost ceilings,
credential separation and working task-owned termination. Source defaults are
not billing authorization or enforced provider caps. Respect source quotas and
Retry-After; stop affected live work on denial, persistent throttle or uncertainty.
See the runbook's WP-14 procedure for commands and isolated fault boundaries.

## WP-15 source verification — 2026-11-20

Operator authorized implementation through WP-16, accepted the visual reference,
and deferred user qualification/live testing until the end of M3. Earlier live
gates remain pending; no provider calls, host deployment or release tag.

CPython 3.12.14, locked dependencies, disposable PostgreSQL 18.6, isolated random
schemas, controlled Git remote, executable CLI fixtures and real HTTP over Unix
sockets. Unit discovery: **18 passed**. WP-15 artifact/intake checks: **5 passed**
(3 artifact, 2 intake). The existing one-package regression: **6 passed** before
adding reviewer-side evidence materialization; final cross-package regressions
are recorded below with WP-16. Wheel 0.3.0 built and installed during development.

Observed: verification produced ready FileRefs; operator download matched
SHA-256/length; wrong principal/claim failed; duplicate uploads converged;
interrupted body streams, wrong digest/metadata, unsafe decoded names and oversized
lengths did not expose ready files. After a lost committed-upload receipt, reopening
the fsynced journal replayed the transfer/final with the original attempt and
exactly one verifier launch. Tests never inserted artifact metadata manually.

## WP-16 source verification — 2026-11-20

Design acceptance is recorded in DESIGN.md and ADR 0007. Source work through
WP-16 is implemented as package **0.4.0**. Live/user qualification is deferred to
the end of M3 (WP-17), including the outstanding earlier gates. No milestone tag,
provider inference, GitHub publication or deployment was performed by these tests.

Final environment: CPython **3.12.14**, PostgreSQL **18.6**, hash-locked dependencies.
The complete integration collection passed in three bounded unittest batches:

- **23 passed:** artifacts (4), browser (5), debug (5), execution (3), intake (2),
  Store (3), runner transport (1).
- **20 passed:** one-package (6), phase scheduling (5), recovery (7), repository (2).
- **5 passed:** interview/debate.

Total **48 integration tests passed**. Following the final test cleanup and late
unknown-owner assertion, browser discovery passed again (**5**) and the changed
artifact recovery case passed (**1**). Unit discovery: **18 passed**. Compileall
and `git diff --check` passed. The 0.4.0 wheel built and installed; dependency
compatibility passed, offline installed CLI help/version worked, and isolated
installed-package checks found Jinja templates, local htmx/license and migration
002. An earlier monolithic regression run ended without a complete summary; the
bounded batches above supersede it. Initial fixture artifact-root/migration
expectations and reviewer snapshot preparation were corrected before final passes.

Browser HTTP checks exercised real committed intake, answers, eligible steering,
pending cancellation and confirmed stop, unknown ownership and reasoned
abandonment, usage projections, PR handoff and SHA-256-matching artifact download.
Checked exact/missing/duplicate/wrong Serve identities, wrong Host and Origin,
bearer substitution, forged CSRF, repeated and conflicting action UUIDs, escaped
log data, local assets, real SSE IDs/replay, more than 100 events without cursor
skips, and reset for invalidated/future cursor. Migration 002 provides the retained
cursor floor; actual retention maintenance belongs to WP-19. Disconnect cleanup
is shielded to finish short database reads/listener release.

Artifact recovery additionally covers replay after abandonment: stale uploads
are durably discarded, stale finals remain audit-only, and a replacement can
finish. Independently validated late logs resolve a current unknown verifier
without launching it again. Reviewers retrieve digest-checked logs only through
their current claim and receive read-only evidence files before execution.

Visual inspection used credential-free headless **Google Chrome 156.0.8078.47**
against a local fixture Serve proxy and a real fixture-produced delivered phase.
Inspected native screenshots: overview light 1440×900; phase light 1366×768;
phase dark 1440×900; intake light 1366×768. Observed the accepted fixed sidebar,
centered stacked content, theme control, compact tables, lifecycle rail, exact PR
handoff and evidence rows without horizontal page overflow. This is local visual
QA, not qualification of real Serve forwarding, OS identities, MyPC/Chromebook,
provider behavior, screen readers or production readiness. Those remain WP-17.

## Container replacement — 2026-11-20

Baseline freshly cloned `main` was clean at `38ea8edec7a1d3bcbe9cebad9e041168eb117867`.
GitHub confirms PR #5 merged at that commit. PR #6 was open/unmerged at
`20831cffc28ff6452788409a3d5581800f6701ad`; the operator explicitly rejected it.
This implementation starts from main, not its account pool or discarded repair.
ADR 0009 and the findings matrix record decisions, evidence and remaining gates.
No WP-17 live acceptance, VPS changes, native credential access or inference.

Local environment: CPython 3.14.4, PostgreSQL 18.6, hash-locked offline Python
wheelhouse. New task-owned database `/tmp/cursus-container-pg`, loopback port
55439; tests create/drop only their random schemas. Native CLIs and GitHub are
controlled executable/API fixtures. Runtime lifecycle fixtures create real local
`sleep` processes but simulate Podman management: they do **not** prove kernel,
container, mount, UID or cgroup isolation. Old direct execution fixtures use the
same UID explicitly and cannot activate the production account backend.

Verification commands (using the task virtual environments):

- Unit discovery: **32 passed**, including setup plans/rejection, native capability
  contracts, constructor without account inventory, same-boot surviving process,
  identity collision, missing-ledger reconstruction, cleanup retries, verifier
  reserve, bounded history and unknown-final receipt ordering.
- Artifact/browser/intake/runner-transport/interview-debate batch: **17 passed**.
- Scheduling/one-package/repository/direct-execution batch plus the then-seven
  container cases: **23 passed**. The old workflow portion is 16 cases.
- Final container/debug/recovery/Store batch: **24 passed**, including the then-nine
  container cases. The existing workflow portion is 15 cases.
- Final clean-installed wheel: unit discovery **32 passed** and container/direct-
  execution/intake batch **15 passed** (ten container cases, three CLI-wire cases,
  two intake/bootstrap cases). This includes durable drain and authenticated
  deployment status. Across the batches: all **58 integration cases** passed.
- Both host-script dry-runs, shell syntax, compileall, `git diff --check`, offline
  wheel build/install, installed CLI help/version, dependency compatibility and
  packaged runtime/migration/browser-resource checks passed. Wheel bytes were
  compared with every packaged source file before delivery.

The first monolithic regression run failed three lost-transport exception
assertions after dispatch accidentally swallowed errors. That was corrected;
artifact and recovery reruns passed. Connected container fixtures found the
missing independent-workspace Git import, the provider-lane SQL constraint, and
fixture reconciliation/cleanup-batch assumptions; these were corrected before
final passing runs. These failures are not native-host qualification results.

Podman reports **5.7.0** locally. Its first info attempt could not write the normal
runtime store in the sandbox; a second attempt using task-local storage reached
`cannot clone: Operation not permitted`. No container was launched. This is an
explicit local namespace limitation, not evidence that intended VPS-A cannot run
containers or that containers are too expensive. Source tests cannot establish
native credential refresh, actual rootless userns/cgroups/mounts, applied setup,
real Serve, real GitHub permissions, hardware throughput or live readiness.
Those remain deferred to M3 end. Chromebook enrollment remains later.

The operator approved OS runtime helpers after the license check identified
passt's GPL-2.0-or-later license; no Python libraries were added. Do not label
Podman's entire OS package closure permissively licensed.

After the final unknown-final acknowledgment ordering correction, clean-installed
wheel unit discovery passed again (**32**) and the complete container/artifact
batch passed (**14**). Final wheel SHA-256:
`16e9a469db9a90d34283ff82cfbff79f854b5c518849c96896009fef053725ad`.
Every packaged source file matched the wheel; compileall, shell syntax,
dependency compatibility and diff whitespace checks passed again. These final
checks supersede the earlier wheel for delivery; no live qualification claim.

## Unified installer and README correction — 2026-11-20

Source changes add `install.sh` and its guided Python helper, retaining the
schema-2 immutable staging/activation engine. This is installer-source evidence,
not an applied deployment or native provider qualification.

- `PYTHONPATH=src python3 -m unittest tests.unit.test_setup tests.unit.test_install_entrypoint`:
  12 passed. Includes a fresh temporary home, actual piped shell execution with
  mocked OS/package/Git/privilege boundaries, source acquisition, Unicode/space
  paths, preservation on repeat, no-change plans, argument rejection, config
  round-trips, pinned local role release, auth-directory rejection, private-file
  preservation and a real pseudo-terminal question/answer check.
- Both unified host dry-runs passed; legacy installer regression tests passed.
  Bash syntax, Python compilation, README local links/anchors and 53 shell block
  syntax checks passed. These are syntax/fixture checks, not execution of the
  manual provisioning commands.
- Earlier full unit discovery in the system Python ran 38 tests: 37 passed,
  installed-entrypoint check errored because `/usr/bin/cursus` is absent. This
  shell has no installed project environment. An isolated environment was created,
  but offline installation of the pinned build backend could not proceed because
  it was unavailable in the local cache. No network dependency install was used
  to mask that limitation. Additional installer tests were then added and passed
  in the targeted run above; the full installed-package suite was not rerun.
- No VPS package/account/service changes, provider inference, native credential
  enrollment, Tailscale changes or real GitHub publication tests were performed.
  A qualified native image/profile/auth domains remain explicit prerequisites;
  the installer does not manufacture them or assert end-to-end readiness.
