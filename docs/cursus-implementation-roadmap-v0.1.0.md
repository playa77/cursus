# Cursus — Implementation Roadmap

**Document** 3 of the Cursus specification set  
**Version** 0.1.0  
**Date** 2026-11-19  
**Status** Draft  
**Normative baseline** Cursus — Design Document v0.1.0 and Cursus — Technical Specification v0.1.1

In this roadmap, **D1 §n** refers to **Cursus — Design Document v0.1.0 §n**. **D2 §n** refers to **Cursus — Technical Specification v0.1.1 §n**. S01–S09 and A1–A7 refer to D2 §§1 and 14. T01–T10 refer to D2 §15.2. All paths are repository-relative.

## 1. Roadmap Overview

Execute one work package per agent session in listed order. For each session, load D1, D2 and this roadmap, confirm predecessor acceptance evidence, implement the assigned package and run its named verification. Keep one commit per work package. The mainline between milestones must build, with incomplete features inaccessible as production capabilities. Each milestone cut has an end-to-end verification.

| Phase | Packages | Runnable outcome |
| --- | --- | --- |
| M0 — Provisioning | WP-01–02 | Packaged Python baseline, tagged repo, host identities and native CLI authentication proven |
| M1 — One package | WP-03–09 | Local CLI input on VPS-B reaches a verified GitHub PR, with one VPS-A runner |
| M2 — Phases | WP-10–14 | Parallel phases, durable recovery, structured debates, and iterative debugging |
| M3 — Browser | WP-15–17 | Tailnet-only browser control and evidence download using the approved visual reference |
| M4 — Non-code and operations | WP-18–20 | Reviewed non-code outputs, backup and restore, full real-work release qualification |

**[CONFLICT]** D2 v0.1.0 blocked all claims in restore drain while publication recovery required a runner-side job. D2 v0.1.1 §§6.3, 9 and 15.2 limit drain admission to read-only publication reconciliation after runner recovery. WP-19 implements and tests that corrected contract. WP-13 also uses the explicitly defined rationale response in D2 v0.1.1 §8.2. D2 v0.1.1 §13 pins the CLI parameters used by the checkpoint commands.

**External inputs.** The documents close the implementation contracts. Live qualification still requires operator-controlled VPS access, provider subscriptions and native credentials, authorized GitHub test/work repos and inputs, and an approved ReUI visual reference for WP-16. These are provisioning or design inputs already required by D1 §§7–8, 11 and D2 §§4, 12–14. Do not invent account secrets, real-work inputs or a design to clear a gate. Continue other dependency-independent work if an external gate is blocked.

## 2. Global Conventions

**[PROPOSED DESIGN DECISION]** Bootstrap the package and changelog before services, services before external integration, and controlled integration before live qualification. Keep Python and htmx dependency versions and license evidence with the release. Use local topic branches named `wp/NN-short-title` from the latest accepted predecessor state, integrate in dependency order, and keep one reviewable commit per WP. Commit subject begins `WP-NN`. Release checkpoints update the changelog in their own WP commit and receive annotated SemVer tags. Never treat a tag or commit's existence as evidence its scenario passed.

Required for each WP:

1. Check dependencies using the artifacts and observed results named in §3. Confirm required services/credentials and selected external fixtures before running the commands.
2. Implement only the scoped paths and public contracts. Use D2 §15 named seams for cross-module calls. Maintain Python style and file size rules from D1 R11. Use complete files, with straightforward error handling and comments for invariant-sensitive code.
3. Add or update the named tests. D2 §12 is binding. Tests establish state through the production path, never by directly inserting claims, candidates, evidence, artifact metadata, or publication intents. External fixtures may emulate a CLI, GitHub, network fault or provision an isolated repo. A test using external fixtures is not proof of a real credential, permission or provider capability.
4. Run the WP verification and the regression suites available at that point. Commands below are run from the repository root in the package environment created by WP-01. Each named discovery command must execute at least one test and exit 0. Record pass counts, assertion outcomes and appropriate commit/phase/attempt or external reference IDs in the applicable qualification record. Never record secrets.
5. Keep any unsupported entry points outside the enabled milestone. Do not hide a test failure by bypassing its predecessor. If a primary trace is impossible under D2, record **[CONFLICT]**, resolve it in a versioned D2 revision, and re-run affected checks before marking the WP done.

**Verification environment.** WP-01 introduces `tests/unit/test_bootstrap.py` and shared fixtures in `tests/support.py`. WP-03 extends the shared fixture for empty PostgreSQL and controlled transactions; WP-06 adds a trusted Git repo and fake external GitHub boundary; WP-07 adds executable agent boundary fixtures. Integration suites start real Cursus services with an empty test DB/state root and these isolated boundaries, unless a test names an intended live VPS check. Reset only disposable test state. `python -m unittest discover -s tests/unit` and `python -m unittest discover -s tests/integration` are the regression commands once each suite has been introduced. Define host/role/user and path values in the provisioned configs and `ops/runbook.md`. In commands, INPUT_PATH and M1_INPUT are absolute paths to D2 §5 Input JSON. PHASE_ID is copied from the preceding successful submit response. No command depends on an uncreated scenario record.

## 3. Dependency Graph

“Parallel” means the listed package can be prepared concurrently with the named peer after both prerequisites are met. Default consumption is serial. Integrate overlap, if introduced by subdivision, in the specified dependency order and re-run both packages after integration.

| ID | Phase | Title | Direct dependencies | Required runtime outputs before verification | Parallel |
| --- | --- | --- | --- | --- | --- |
| WP-01 | M0 | Bootstrap contracts and Python package | — | CPython and build environment | — |
| WP-02 | M0 | Provision hosts and CLI identities | WP-01 | Intended hosts, tailnet, credentials | — |
| WP-03 | M1 | Durable storage and transaction primitives | WP-02 | Empty test PostgreSQL, installed package | — |
| WP-04 | M1 | Intake and private service ingress | WP-03 | Real migrations, same-origin ingress, initial workflow wiring | — |
| WP-05 | M1 | Runner polling, journal and event transport | WP-04 | Live test service, enrolled test runner identity | WP-06/WP-07 |
| WP-06 | M1 | Worktrees, scoped refs and GitHub operations | WP-04 | Disposable trusted repo, controlled GitHub fixture | WP-05/WP-07 |
| WP-07 | M1 | CLI execution, verification and independent review | WP-04 | Executable boundary fixtures, measured role/profile schema | WP-05/WP-06 |
| WP-08 | M1 | One-package workflow to PR | WP-05, WP-06, WP-07 | Started services, repo/blob reads, launch and review, publisher | — |
| WP-09 | M1 | Qualify the real single-package path | WP-08 | M0 identities, actual registered repo and Go/CLI credentials | — |
| WP-10 | M2 | Package scheduling and integration sequencing | WP-09 | Proven single-package path and disposable overlapping Git changes | — |
| WP-11 | M2 | Reconciliation and uncertain outcomes | WP-10 | Real claim/event pipeline and publisher effects from a production intent | — |
| WP-12 | M2 | Iterative pi debugging and durable steering | WP-11 | RPC and separate verifier capacity, actual checkpoint refs | — |
| WP-13 | M2 | Guided interviews and structured debate | WP-12 | Frontier invocation qualification and existing operator action path | — |
| WP-14 | M2 | Qualify phased, recovery, debug and debate paths | WP-13 | Active real phase, separate VPS processes and qualified roles | — |
| WP-15 | M3 | Artifact ingest, access and evidence handoff | WP-14 | Active verification attempt and file-emitting evidence path | — |
| WP-16 | M3 | Server-rendered browser and SSE | WP-15 | Approved ReUI reference, committed operator events, downloadable evidence | — |
| WP-17 | M3 | Qualify the tailnet browser release | WP-16 | Real Serve identity, MyPC/Chromebook, active and delivered phases | — |
| WP-18 | M4 | Built-in non-code workflows | WP-17 | Verified artifact transport, working review, enrolled workflow inputs | — |
| WP-19 | M4 | Observability, backup, retention and restore | WP-18 | Real pipeline-produced records/files, previous remote intent, backup storage | — |
| WP-20 | M4 | Qualify v1 and tag release | WP-19 | Real work and actual credentials, two running VPSs, browser clients | — |

The listed graph strictly points backward. WP-05–07 are preparation branches only and do not each require the others' runtime implementations for their own tests.

## 4. Work Packages

### WP-01 — Bootstrap contracts and Python package · M0

**Depends on** None.  
**Objective** Establish a reproducible Python package, contract primitives, and test entry point. This lets every later WP run against the same package and type definitions.

- **Scope** Create `pyproject.toml`, `requirements.lock`, `CHANGELOG.md`, `src/cursus/bootstrap.py`, `src/cursus/contracts.py`, `tests/support.py`, and `tests/unit/test_bootstrap.py`. Excludes services, DB and host credentials.
- **Spec** D1 §§2, 8; D2 §§2–5.1, 8.1, 13.
- **Tasks** 1. Set up package metadata and build/entry point. 2. Lock permissive dependencies and record license checks. 3. Define common validators and stable errors for scalar, discriminator and canonical serialization. 4. Provide the basic test workspace constructor and bootstrap help path.
- **Contracts** Consumes CPython/build inputs. Produces installable package, bootstrap entry point, shared validation, and test workspace fixture. Service calls become available only in their assigned packages.
- **Acceptance** A clean wheel builds and installs. Bootstrap help starts without DB or credentials. Validation rejects duplicate keys, illegal refs and wrong variants.
- **Verify** `python -m build --wheel`; `python -m pip install --no-deps --force-reinstall dist/cursus-*.whl` in the clean WP package environment; `cursus --help`; `python -m unittest discover -s tests/unit -p 'test_bootstrap.py'`. Expect wheel output, usable help, and passing validator tests.
- **Sizing** One session. Packaging and stateless contracts only.

### WP-02 — Provision hosts and CLI identities · M0

**Depends on** WP-01.  
**Objective** Establish the actual tailnet, service identities and native provider authentication needed for later qualification.

- **Scope** Create `deploy/control.example.toml`, `deploy/runner.example.toml`, `deploy/capabilities.example.toml`, `ops/runbook.md`, `tests/qualification.md`; update `CHANGELOG.md`. Provision intended VPSs and clients. Excludes control/runner services and exposure of browser routes.
- **Spec** D1 §§7–8, 11; D2 §§3–4.1, 7, 13–14.
- **Tasks** 1. Record host roles, addresses, CPython and PostgreSQL availability, service accounts and isolated roots. 2. Pair MyPC and Chromebook to the private tailnet. 3. Install four CLIs and provision each native credential under its designated user. 4. Record binaries, identity, version, renewal and non-interactive smoke outcomes, without secrets. 5. Record no public ingress and M0 release evidence.
- **Contracts** Consumes bootstrap package and operator credentials. Produces live host/auth prerequisites, consistent config names and a qualification log. It does not yet qualify tool behavior or start Cursus jobs.
- **Acceptance** Each assigned CLI under its service identity returns a minimal successful non-interactive response on VPS-A. Both operator devices reach the private tailnet. Intended PostgreSQL and deployment directories are available.
- **Verify** On VPS-A run `tailscale status`; on VPS-B run `pg_isready` and `tailscale status`. Under each service identity run the literal minimal headless invocation recorded in `tests/qualification.md` during this WP, using the installed CLI and configured provider/model. Expect four successes with no interactive prompt. Record tailnet access from both devices and tag M0 only after these pass.
- **Sizing** One provisioning session. Native credentials already supplied by the operator. Vendor enrollment issues leave the affected gate blocked.

### WP-03 — Durable storage and transaction primitives · M1

**Depends on** WP-02.  
**Objective** Supply the real DB and transaction seams before APIs create their first durable state.

- **Scope** Create `src/cursus/store.py`, `src/cursus/migrations/001_initial.sql`, `tests/integration/test_store.py`; extend `tests/support.py`, `ops/runbook.md`. Excludes HTTP, runner and browser.
- **Spec** D2 §§5, 8.1, 11–12, 15 T01–T03.
- **Tasks** 1. Apply numbered migrations under lock. 2. Implement atomic state/queue/events/idempotency transactions with the ordered coordination row. 3. Implement claim uniqueness, reads and wakeups. 4. Build a disposable DB fixture driven through Store and its callback contract.
- **Contracts** Consumes accepted data types and empty PostgreSQL. Produces schema, Store migrate/transact/read/wait and committed cursor semantics.
- **Acceptance** Concurrent requests produce ordered committed cursors; rollback leaves no partial claim or cursor advance; reapplying migration is safe and digest mismatch fails.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_store.py'`. The suite provisions DB through migration and calls Store to produce state before exercising reads, uniqueness or rollback.
- **Sizing** One session for schema, transaction gates and a DB fixture.

### WP-04 — Intake and private service ingress · M1

**Depends on** WP-03.  
**Objective** Make the control plane admit and show a run through its authorized interfaces.

- **Scope** Create `src/cursus/config.py`, `src/cursus/http.py`, `src/cursus/control.py`, `src/cursus/workflows.py`, `roles.toml`, `prompts/interviewer.md`, `prompts/planner.md`, `prompts/worker.md`, `prompts/reviewer.md`, `deploy/cursus-control.service`, `tests/integration/test_intake.py`; update `src/cursus/bootstrap.py`, `src/cursus/contracts.py`, `ops/runbook.md`. Excludes browser rendering and runner execution.
- **Spec** D1 §§4, 6–7; D2 §§4–7, 8.1–8.3, 13, 15 T01.
- **Tasks** 1. Load validated control settings and pin role/prompt revision. 2. Wire single composition root. 3. Bind dedicated authorized Unix socket and private loopback, plus bounded request decoding. 4. Implement preliminary submit/status/action and create queued resolution/plan work via the transaction. 5. Reject unsupported features until their gate exists.
- **Contracts** Consumes Store and contracts. Produces `cursus submit/status/action`, operator route, initial job creation, authorized read, config validation and workflow selection entry point.
- **Acceptance** An authorized submission commits one phase and its first queued job, and retry returns the same identity. Invalid body or identity cannot create state. No start/PR claim is made at this stage.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_intake.py'`. Expect committed phase through real socket and unchanged state after denied inputs.
- **Sizing** One session, limited to an intake/read slice and auth skeleton.

### WP-05 — Runner polling, journal and event transport · M1

**Depends on** WP-04.  
**Objective** Establish an authenticated runner connection and durable claim/report transport ahead of actual CLI or Git dispatch.

- **Scope** Create `src/cursus/runner.py`, `deploy/cursus-runner.service`, `tests/integration/test_runner_transport.py`; update `src/cursus/http.py`, `src/cursus/control.py`, `src/cursus/store.py`, `src/cursus/contracts.py`, `src/cursus/bootstrap.py`. Excludes CLI/Git production and failure recovery beyond the first claim/replay contract.
- **Spec** D2 §§5–7, 8.1, 8.4, 11–12, 15 T02–T03.
- **Tasks** 1. Add authenticated generation-scoped reconcile, heartbeat, long-poll and ordered event ingestion. 2. Persist runner generation, pending poll, claim and event positions. 3. Recover a repeated request UUID and detect evicted or absent job state. 4. Add idle service integration and transport faults at handoff points.
- **Contracts** Consumes actual control startup and operator intake. Produces runner HTTPS exchange, locally journaled grant, contiguous event ack and command feed envelope.
- **Acceptance** Connected idle runner claims nothing from empty queue. A queued resolve job produced by operator intake is granted once and stored on disk. Reissuing the same grant request never inserts a second claim. An out-of-order event is rejected.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_runner_transport.py'`. Use a controlled boundary after claim dispatch. Stop at the journaled grant and check its replayed request UUID. Send a deliberately invalid event sequence as a negative boundary test. Positive process-produced event replay is exercised by WP-08 and WP-11.
- **Sizing** One session for transport and happy-path persistence. Cross-service interruption handling is WP-11.

### WP-06 — Worktrees, scoped refs and GitHub operations · M1

**Depends on** WP-04.  
**Objective** Implement isolated repo operations and the conditional publisher before connecting them to job scheduling.

- **Scope** Create `src/cursus/repository.py`, `tests/integration/test_repository.py`; extend `tests/support.py`, `ops/runbook.md` Git fixture/setup. Excludes state-machine authorizations, debug loop and browser.
- **Spec** D2 §§4, 7, 8.2, 8.5, 11–12, 15 T02/T05.
- **Tasks** 1. Fetch allowed refs and blob inputs at fixed SHAs. 2. Create worktree and read-only snapshots. 3. Capture a candidate on its exact attempt ref. 4. Test staged integration and expected-head checks on Git. 5. Implement runner-owned GitHub PR lookup, creation and named reconciliation result, including unexpected closed PR and ambiguous responses.
- **Contracts** Consumes validated Repo and Job input types, controlled external Git/GitHub fixtures. Produces `repository.perform` for resolution, workspace, candidate, staging, conditional ref and PR operations. Real intent creation is WP-08.
- **Acceptance** Actual Git worktree operation produces the candidate from a repo change. Duplicate operations reuse exact effects; target or out-of-enrollment writes are refused. Boundary fixture confirms only intended REST operations.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_repository.py'`. Git state is created via the repository operation under test. REST seam tests use a request contract and fixture, with the end-to-end authorization producer tested in WP-08.
- **Sizing** One session for an isolated Git/publisher module and its boundary tests. No service wiring.

### WP-07 — CLI execution, verification and independent review · M1

**Depends on** WP-04.  
**Objective** Execute pinned agent binaries and real repository checks under the identities and input limits required by D2.

- **Scope** Create `src/cursus/execution.py`, `tests/integration/test_execution.py`, `prompts/scout.md`; update `deploy/capabilities.example.toml`. Keep executable fixture definitions in `tests/integration/test_execution.py` for reuse by its importing integration tests. Excludes durable checkpoint loops and debate scheduling.
- **Spec** D1 §§3–4, 7, 11; D2 §§4.1, 7–8.3, 11–12, 15 T02/T04/T05.
- **Tasks** 1. Implement fixed direct argv, credential and process isolation for pi, Claude, Codex and Antigravity profiles. 2. Frame and normalize structured output, terminal response, RPC request correlation and time limits. 3. Execute approved verifier argv and collect evidence. 4. Require independently validated review verdict and render a sanitized log stream.
- **Contracts** Consumes typed Job/Invocation, workspace path and execution identity. Produces `execution.run` and controlled CLI executable fixtures. Live profile proof is WP-09.
- **Acceptance** Role/tier or profile mismatch rejects launch. Real fixture processes emit completion/denials. A grader cannot pass a missing report or invalid review. No fixture subprocess sees launcher secrets.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_execution.py'`. Expect executable fixtures to exercise four wire shapes and real verifier exit/evidence production. Host identity proof remains an actual VPS check.
- **Sizing** One session devoted to process boundary, profile transport and parsing. No orchestration changes.

### WP-08 — One-package workflow to PR · M1

**Depends on** WP-05, WP-06, WP-07.  
**Objective** Join the finished seams to deliver a single reviewed package autonomously.

- **Scope** Update `src/cursus/bootstrap.py`, `src/cursus/runner.py`, `src/cursus/control.py`, `src/cursus/workflows.py`, `src/cursus/contracts.py`, `roles.toml`; create `tests/integration/test_one_package.py`. Excludes parallel plans, full reconnect recovery, interview/debate and UI.
- **Spec** D2 §§6, 8.1–8.5, 12–13, 15 T01–T05.
- **Tasks** 1. Wire repo reads, stage/verification/execution and publisher into the actual runner dispatch. 2. Resolve exact base and repo file input. 3. Plan one approved package, run pi, capture and verify exact SHA, independently review, then stage and verify combined candidate. 4. Commit publication intent before push/PR; confirm exact results. 5. Apply bounded repair or park. Refuse publication on target drift until WP-10 supplies the automatic revalidation path.
- **Contracts** Consumes transport, Repo and Execution seams. Produces committed candidate/evidence/verdict, authorized publication, integrated head and PR identity. No initial work state is seeded.
- **Acceptance** CLI inline and pinned repo inputs both reach a verified PR in controlled end-to-end runs. Failure cases cannot write the target branch or publish without evidence.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_one_package.py'`. Expect real service/runner traces T01–T05, exact head SHA, one confirmed PR, and unchanged target.
- **Sizing** One integration session. Component code and fixture dependencies exist already.

### WP-09 — Qualify the real single-package path · M1

**Depends on** WP-08.  
**Objective** Prove the selected technologies and authorization boundaries on the two actual VPSs.

- **Scope** Update `deploy/capabilities.example.toml`, `ops/runbook.md`, `tests/qualification.md`, `CHANGELOG.md`; deploy configuration and process services to intended hosts. Excludes new runtime features. Correct supported config or version incompatibility before tagging.
- **Spec** D1 §§8, 11; D2 §§4.1, 7, 12–14.
- **Tasks** 1. Record measured flags, models, output, process control and credential isolation under exact identities. 2. Prove pi OpenCode Go tool call and RPC steer/abort, headless Claude/Codex/Antigravity with structured read-only behavior, and Serve identity on both clients using a minimal probe. 3. Enroll authorized repo, run real single-package spec from VPS-B CLI, and verify exact GitHub handoff. 4. Document qualification and tag M1.
- **Contracts** Consumes real auth from WP-02 and connected system from WP-08. Produces pinned capability measurements and real end-to-end evidence used later.
- **Acceptance** All mandated CLIs qualify. Real one-package work produces a reviewed PR and no target update. Tailnet identity probe rejects missing/forged identity.
- **Verify** Run `systemctl status cursus-control` on VPS-B and `systemctl status cursus-runner` on VPS-A. Run `cursus submit --help` on VPS-B and `cursus submit --input "$M1_INPUT"`; `cursus status --phase-id "$PHASE_ID"`; then run the exact per-CLI probe commands recorded in `tests/qualification.md` by WP-09. The runbook defines the Input JSON file and how to read the returned phase ID. Expected terminal state is delivered, one PR with verified head and evidence. Do not tag with a failed capability probe.
- **Sizing** One host qualification session after credentials and trusted test repo are ready.

### WP-10 — Package scheduling and integration sequencing · M2

**Depends on** WP-09.  
**Objective** Deliver a multi-package phase with parallel work, evidence tied to actual inputs, and a serialized integration lane.

- **Scope** Update `src/cursus/workflows.py`, `src/cursus/control.py`, `src/cursus/store.py`, `src/cursus/repository.py`, `src/cursus/contracts.py`; create `tests/integration/test_phase_scheduling.py`. Excludes disconnect injection and debug control.
- **Spec** D1 §§3–6; D2 §§5, 8.2–8.5, 12, 15 T05.
- **Tasks** 1. Validate graph and delivery groups. 2. Schedule ready packages in plan order and enforce per-slot bounds. 3. Serialize integration per lane, verify combined tree and seek fresh review for a material delta. 4. Release dependents from a committed head. 5. Recheck target drift, retry bounded overlap and reconcile delivery as specified.
- **Contracts** Consumes one-package end-to-end producer and real stage/ref operations. Produces multi-package and independent group planning, lane heads, dependency release and complete delivery disposition.
- **Acceptance** Parallel attempts use distinct worktrees and refs. A dependent job starts only after its prerequisite integrates and sees the correct head. An overlap repairs or parks within budget. Target drift cannot declare an unchecked PR delivered.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_phase_scheduling.py'`. The suite submits plans through the actual planning result path and changes the controlled remote using Git operations. Assert overlap, dependent base, disjoint refs, serialized integration and exact final PR heads.
- **Sizing** One workflow extension session. Reuse all publisher and verifier seams.

### WP-11 — Reconciliation and uncertain outcomes · M2

**Depends on** WP-10.  
**Objective** Recover actual claims, commands and remote effects after interruption without duplicate execution or an unsafe retry.

- **Scope** Update `src/cursus/runner.py`, `src/cursus/control.py`, `src/cursus/workflows.py`, `src/cursus/store.py`, `src/cursus/http.py`, `src/cursus/repository.py`, `src/cursus/contracts.py`, `ops/runbook.md`; create `tests/integration/test_recovery.py`. Excludes restore from backup and debug-specific command transport.
- **Spec** D1 §§5–6, 9; D2 §§5–6, 8.3–8.5, 9, 11–12, 15 T02/T03/T08.
- **Tasks** 1. Reconcile lost claim response and journal before re-admission; deduplicate lost ack. 2. Separate liveness from ownership. 3. Observe old process/boot/service identity to prove a stop where possible. 4. Implement cancel, unknown parking and exceptional abandon. 5. Reconcile ambiguous ref/PR operations through the recorded intent.
- **Contracts** Consumes production claims, spool, effects and prior Git promotion/PR intents. Produces observed recovery dispositions, one effect on replay, bounded interrupted retry and explicit abandonment. Retains restore descriptors used by WP-19.
- **Acceptance** Restart or link loss reuses current attempt and replays events. Proven stop permits a new eligible attempt. Unknown retains ownership and only explicit abandonment permits retry. Delayed results never advance abandoned work. A remote result with a lost ack has no second mutation.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_recovery.py'`. Inject faults at actual claim commit, event ack, process lifecycle and ref/PR response boundaries. Inspect persisted outcome via operator/runner reads.
- **Sizing** One recovery-focused session with existing production entry points. Cover deterministic fault cases before real VPS checks in WP-14.

### WP-12 — Iterative pi debugging and durable steering · M2

**Depends on** WP-11.  
**Objective** Drive repeated debugging turns and verifications in one pi RPC process and finish autonomously.

- **Scope** Update `src/cursus/execution.py`, `src/cursus/runner.py`, `src/cursus/repository.py`, `src/cursus/contracts.py`, `src/cursus/control.py`, `src/cursus/workflows.py`, `roles.toml`; create `prompts/debug.md`, `tests/integration/test_debug.py`. Excludes browser controls and multi-process resumed sessions.
- **Spec** D1 §§3–4, 9; D2 §§4.1, 8.2–8.5, 12, 15 T06.
- **Tasks** 1. Add debug role, checkpoint capture and typed event. 2. Schedule verify in the separate slot while the parent retains ownership. 3. Feed failing evidence to the same process or finish at exact passing checkpoint. 4. Persist steer/continue/finish/stop dispositions, including uncertain command delivery. 5. Reuse review/integration/PR pipeline.
- **Contracts** Consumes pinned RPC execution, event/command envelopes, repo refs, verified evidence and recovery. Produces continuing debug checkpoint loop, effective steering, autonomous completion.
- **Acceptance** A real controlled failing project check fails on an earlier checkpoint, succeeds on a later checkpoint of the same attempt, and produces reviewed PR without confirmation at finish. Disconnect/replay and cancel preserve disposition.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_debug.py'`. Verify same RPC process across turns, two executed verification outcomes and one reviewed PR at the fixed SHA.
- **Sizing** One session for debug-specific lifecycle; reuse the production scheduler and publication.

### WP-13 — Guided interviews and structured debate · M2

**Depends on** WP-12.  
**Objective** Add guided spec formation and optional three-seat debate without changing normal direct intake.

- **Scope** Update `src/cursus/contracts.py`, `src/cursus/control.py`, `src/cursus/workflows.py`, `roles.toml`, `prompts/interviewer.md`, `prompts/planner.md`; create `prompts/advocate.md`, `prompts/critic.md`, `prompts/judge.md`, `tests/integration/test_interview_debate.py`. Excludes browser form presentation.
- **Spec** D1 §§3–4, 6; D2 §§4, 6.2, 8.2–8.3, 15 T04.
- **Tasks** 1. Commit questions and answers by revision. 2. Validate completed specs and bounded scout request/reply. 3. Freeze three distinct frontier roles; launch and persist rationale, objections, reply, judgment and amendment stages. 4. In spec mode feed operator answers back into the next round. 5. Enforce three-round bound and park unresolved plans.
- **Contracts** Consumes frontier job execution and operator action API. Produces guided intake, bounded scout and per-round immutable seat transcript and verdict.
- **Acceptance** Usable interviewer path queues plan only after required questions resolve. A debate receives correct context per seat, rejects wrong shape or seat, validates amendments before progression, and parks at cap. Non-debated input still flows.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_interview_debate.py'`. Drive submissions and answers through the CLI/socket and controlled frontier results through actual attempts. Inspect committed transcripts and jobs.
- **Sizing** One session for prompt contracts and durable intake/debate transitions over existing execution.

### WP-14 — Qualify phased, recovery, debug and debate paths · M2

**Depends on** WP-13.  
**Objective** Prove the M2 execution paths with qualified CLIs and the actual VPS process boundaries.

- **Scope** Update `tests/qualification.md`, `ops/runbook.md`, `CHANGELOG.md`; create no runtime modules. Use dedicated trusted work and record evidence. Excludes browser and non-coding handoff.
- **Spec** D1 §§8–9; D2 §§12–15, A1–A4 and debate part of A7.
- **Tasks** 1. Run real five-package phase, including overlapped pi work and dependencies. 2. In a separate recovery run, interrupt control service and the link under an active attempt; observe retention and replay. 3. Exercise proven runner interruption and the unknown/abandon path on isolated disposable work. 4. Run real iterative debug and optional distinct-seat debate. 5. Record and tag M2.
- **Contracts** Consumes actual runner and PostgreSQL, live work repository, qualified frontier/pi profiles. Produces real phase/recovery/debug/debate evidence and M2 tag.
- **Acceptance** Real runs support A1–A4 with identities, logs and heads. Recovery interventions are kept out of the zero-intervention run. Actual seat identities in debate are distinct.
- **Verify** `python -m unittest discover -s tests/integration`; run `cursus submit --input "$INPUT_PATH"` once for each of the M2 phase, recovery, debug and debate inputs recorded in `tests/qualification.md`. Inspect each returned phase with `cursus status --phase-id "$PHASE_ID"`. In the recovery run, on VPS-B execute `sudo systemctl restart cursus-control`; verify an unchanged live attempt ID through status before and after and resume to delivered. Use the runbook's isolated link fault and runner restart checks, and record exact commands and durations. Expect corrective evidence or explicit parked disposition in the intended case.
- **Sizing** One qualification work package. Runs may take time but require no implementation expansion.

### WP-15 — Artifact ingest, access and evidence handoff · M3

**Depends on** WP-14.  
**Objective** Produce an actual downloadable evidence file before browser download verification and non-code pipeline work.

- **Scope** Create `src/cursus/artifacts.py`, `tests/integration/test_artifacts.py`; update `src/cursus/bootstrap.py`, `src/cursus/contracts.py`, `src/cursus/control.py`, `src/cursus/http.py`, `src/cursus/store.py`, `src/cursus/runner.py`, `src/cursus/execution.py`, `src/cursus/repository.py`. Excludes non-code workflow activation and backup cleanup.
- **Spec** D1 §§5–6; D2 §§5–7, 8.1/8.3/8.5, 12, 15 T07/T09.
- **Tasks** 1. Implement bounded artifact collection, durable file staging and metadata commit. 2. Implement idempotent upload and claim-scoped download; confirm digest. 3. Attach a verifier evidence log FileRef through the running code workflow. 4. Expose authorized download by ready FileRef. 5. Exercise duplicate requests, mismatches, interruptions and unsafe paths.
- **Contracts** Consumes a real verification attempt producer. Produces immutable file bytes/metadata, transfer API, ready FileRef delivered by production verification and availability for the browser.
- **Acceptance** Code verification emits a ready evidence log. An authorized caller retrieves identical bytes. Interrupted or conflicting metadata is reconciled or rejected. No download can be accepted against hand-built metadata.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_artifacts.py'`. Run from intake through verification, capture returned FileRef, check hash after download and exercise wrong principal and claim.
- **Sizing** One session for artifact pipeline and one existing producer. Non-code acceptance is WP-18.

### WP-16 — Server-rendered browser and SSE · M3

**Depends on** WP-15 and the approved ReUI reference.  
**Objective** Expose existing operator actions and live committed state through the private web address.

- **Scope** Update `src/cursus/bootstrap.py`, `src/cursus/http.py`, `src/cursus/control.py`, `src/cursus/store.py`, `ops/runbook.md`; create `src/cursus/templates/base.html`, `src/cursus/templates/index.html`, `src/cursus/templates/phase.html`, `src/cursus/templates/attempt.html`, `src/cursus/templates/problem.html`, `src/cursus/static/htmx.min.js`, `src/cursus/static/htmx.LICENSE`, `src/cursus/static/events.js`, `src/cursus/static/cursus.css`, and `tests/integration/test_browser.py`. Excludes designing the visual reference, frontend build and client installation.
- **Spec** D1 §§6–8; D2 §§3, 6.1–6.2, 7, 9–10, 15 T09.
- **Tasks** 1. Translate the supplied reference to server-rendered templates and local htmx. 2. Wire authorized forms and real workflow states, IDs and handoff links. 3. Stream committed events by cursor with keepalive, replay and reset. 4. Expose progress, pending/parked dispositions, evidence downloads and PR links. 5. Enforce Serve identity, exact origin and CSRF.
- **Contracts** Consumes production phases, commands, evidence and route authorization; externally approved visual reference. Produces server-rendered browser actions, authorized SSE and artifact/PR access.
- **Acceptance** Browser request path can submit/read/answer/steer/cancel where permitted. Reconnect never duplicates a committed event, expired cursors resync, unauthorized actions fail, and no frontend build is required.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_browser.py'`. Use committed states from exercised intake/recovery/evidence paths; assert the actual SSE cursor and output responses.
- **Sizing** One browser implementation session against an approved reference. A missing reference blocks template work, while final visual choice remains outside the roadmap.

### WP-17 — Qualify the tailnet browser release · M3

**Depends on** WP-16.  
**Objective** Prove the actual browser workflows and authorization from both operator devices.

- **Scope** Update `ops/runbook.md`, `tests/qualification.md`, `CHANGELOG.md`; no runtime modules. Deploy the existing M3 surface. Excludes non-code acceptance and release-wide qualification.
- **Spec** D1 §§7–8; D2 §§6–7, 12–14, A6, 15 T09.
- **Tasks** 1. Start deployed loopback service and Serve private HTTPS ingress. 2. Use MyPC and Chromebook to create and inspect runs, reply to questions and steer an eligible attempt. 3. Observe live events through reconnect and a parked result. 4. Download the evidence file from an actual completed run, then verify checksum and try unauthorized access. 5. Record results and tag M3.
- **Contracts** Consumes real Serve login and CLI/runtime qualifier, browser-ready routes and ready artifact generated via WP-15. Produces verified M3 release.
- **Acceptance** Both devices use existing browsers. The operator can act and read committed outcomes via private Serve. Unauthorized identity/forged header cannot act or fetch bytes. Evidence downloads are from a produced artifact.
- **Verify** On VPS-B run `tailscale serve status`; from each operator browser open the exact provisioned URL in `ops/runbook.md`. Execute the actions listed in this WP and `sha256sum` on the downloaded file with its exact local filename, comparing to recorded FileRef digest. Expect authorization success for the operator and failure for a non-allowed identity. Full non-code deliverable qualification is WP-20.
- **Sizing** One two-device qualification session.

### WP-18 — Built-in non-code workflows · M4

**Depends on** WP-17.  
**Objective** Reuse the verified workflow engine to deliver reviewed marketing, grant and business-development files.

- **Scope** Update `src/cursus/workflows.py`, `src/cursus/contracts.py`, `src/cursus/control.py`, `src/cursus/runner.py`, `src/cursus/repository.py`, `roles.toml`, `src/cursus/templates/index.html`, `src/cursus/templates/phase.html`; create `prompts/marketing.md`, `prompts/grant.md`, `prompts/business.md`, `tests/integration/test_noncode.py`. Excludes external publication and plugin loading.
- **Spec** D1 §§3–6, 8; D2 §§1, 5–8, 12, 15 T07.
- **Tasks** 1. Enable the three built-in task types and pin intake obligations. 2. Plan artifacts/criteria, execute pi and collect bounded files. 3. Fetch exact ready files for verification and independent review; repair or park if required. 4. Commit delivered FileRefs and expose download. 5. Confirm no delivery action leaves Cursus.
- **Contracts** Consumes runner execution, artifact transfer, immutable review and operator UX. Produces all three first-release non-code flows with reviewed results.
- **Acceptance** All three workflows reach resolved, downloadable verified deliverables in integration tests. Bad or rejected files do not pass. No remote distribution or GitHub publication is implied.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_noncode.py'`. Each case submits via production intake and obtains bytes uploaded by a real controlled worker process. Record review result and download digest.
- **Sizing** One session for three configuration/prompt variations over the same runtime path.

### WP-19 — Observability, backup, retention and restore · M4

**Depends on** WP-18.  
**Objective** Operate, back up and restore persisted state with unresolved external effects fenced.

- **Scope** Update `src/cursus/bootstrap.py`, `src/cursus/http.py`, `src/cursus/control.py`, `src/cursus/store.py`, `src/cursus/artifacts.py`, `src/cursus/runner.py`, `src/cursus/contracts.py`, `src/cursus/templates/index.html`, `src/cursus/templates/phase.html`, `ops/runbook.md`, `tests/qualification.md`; create `tests/integration/test_operations.py`. Excludes high availability, automatic host failover and provider switching.
- **Spec** D1 §§8–9; D2 §§6.3, 8.4, 9–13, 15 T08/T10, including v0.1.1 restore admission.
- **Tasks** 1. Complete health, redaction, storage budget and workload status projections. 2. Implement local maintenance socket, file cleanup hold, retention and safe deletion. 3. Configure Hermes nightly procedure and matching DB/file bundle. 4. Restore in drain, reconcile old claims and any authorized read-only publisher inspection, and reopen only after disposition. 5. Verify stale cursor reset and race-safe retention.
- **Contracts** Consumes actual pipeline-populated state, evidence bytes, retained journals, GitHub intent and recovery path. Produces maintenance CLI, qualified restores, monitoring and retention outcome.
- **Acceptance** Restore of a real produced test bundle preserves valid artifacts and can inspect an old ambiguous remote intent with only the read-only job allowed. Normal jobs remain blocked until reopen. Held or orphaned state never authorizes an extra mutation. Saturated runner leaves operator calls responsive.
- **Verify** `python -m unittest discover -s tests/integration -p 'test_operations.py'`; run the literal Hermes backup invocation and `pg_restore --list` against the bundle path recorded by the runbook. Restore only into the disposable qualifying instance, reconnect the runner and verify recovery using the maintenance path. Expect one consistent post-restore disposition, a valid bundle manifest and no second external write.
- **Sizing** One operations session using existing recovery/backup tools and an isolated clone for restore.

### WP-20 — Qualify v1 and tag release · M4

**Depends on** WP-19.  
**Objective** Produce release evidence for every final acceptance criterion against the complete system.

- **Scope** Update `tests/qualification.md`, `ops/runbook.md`, `CHANGELOG.md`; tag the release. Excludes new functionality and target-branch merge.
- **Spec** D1 §§2, 8–9; D2 §§12–14, A1–A7.
- **Tasks** 1. Run both automated suites from a clean deployment environment. 2. Check earlier real-work evidence against pinned versions; rerun affected qualification for changed contracts. 3. Run one actual marketing and grant input and confirm reviewed usable files from both clients. 4. Verify business-development integration coverage, restore, saturation and required CLI proof. 5. Record acceptance matrix and tag M4/v1.
- **Contracts** Consumes prior milestone evidence and only the final production runtime. Produces completed A1–A7 proof and tagged v1.
- **Acceptance** Every A1–A7 entry has passing, attributable evidence, not just a fixture result for a live gate. The release stays within D1 §2 limits.
- **Verify** `python -m unittest discover -s tests/unit`; `python -m unittest discover -s tests/integration`; run the recorded milestone checks as applicable to the final release build. Submit the actual marketing and grant inputs through the approved surface, confirm delivered state, review identity, and digest-matching downloads. Expect all suites and live gates to pass before applying the annotated tag.
- **Sizing** One release qualification session. Failed gates return to the responsible WP instead of expanding release scope.

## 5. Milestones & Integration Checkpoints

| Cut | Required end-to-end smoke procedure | Pass condition |
| --- | --- | --- |
| M0, after WP-02 | Build and install wheel, run bootstrap help, confirm VPS-A CLI logins and VPS-B PostgreSQL reachability, check both operator tailnet clients as in WP-02. | Packaged baseline and native prerequisites available. |
| M1, after WP-09 | Start control and runner services, submit authorized one-package input through local CLI, inspect status and PR head. Repeat controlled tests with denial/repair. | Verified independent review and matching PR. No target write. |
| M2, after WP-14 | Submit separate autonomous phase, recovery, debug and debate runs through the local CLI. Observe durable IDs across control restart and interrupted link. | Real A1–A4 evidence, distinct seats, package/ref isolation and same-session debug. |
| M3, after WP-17 | Use both existing browsers on Serve, send a legitimate action, disconnect/reconnect SSE, inspect parked state, download a verification artifact from a completed run. | Private server-rendered browser path works, correct cursor and digest, unauthorized actions denied. |
| M4, after WP-20 | Run both automated suites, marketing/grant live runs and reviewed file downloads. Exercise backup, restore in drain and real saturation check with verified pinned profiles. | Complete A1–A7 evidence, with reviewed usable deliverables and release tag. |

### Executability trace review

The table follows D2 §15.2 and names the producing packages for each process boundary and durable result. WP verifications occur after the relevant producers. A qualification environment must use the same ingress and ownership path as production.

| Trace | Entry and cross-process chain | Committed state and producers |
| --- | --- | --- |
| T01 | Systemd/bootstrap → config/Store/HTTP → operator socket or, at M3, same-origin request → control → workflow/Store → runner repo resolution when applicable | WP-01–04 create real schema and intake. WP-05/06/08 produce source resolution and plan inputs. Phase/spec/job are committed on VPS-B. |
| T02–T03 | Runner journal → authenticated HTTP claim → Store attempt → spawned Git/CLI/verifier → durable runner event → HTTP/Store transition | WP-05 provides grant, spool and ack; WP-06/07 provide actual callees; WP-08 wires them. Claim and result survive in PostgreSQL, receipts/spool on VPS-A. |
| T04 | Authorized answer → queued frontier job → fresh configured CLI → typed response → workflow next step | WP-07/09 supply qualified CLI executions. WP-13 produces durable question, plan, seat results and amendments. |
| T05 | pi candidate → Git attempt ref → verifier/reviewer → staged integration → durable intent → conditional push/PR → result | WP-06–08 produce single path, WP-10 adds lanes and independent overlap checks, WP-11 recovers ambiguous remote effects. References live on GitHub and are committed in DB. |
| T06 | Active pi RPC checkpoint → Git candidate → separate verifier claim → committed command → runner journal → same pi RPC → exact verified final | WP-07/08 provide execution and checks, WP-11 provides recoverable command feed, WP-12 provides checkpoint-to-command caller. |
| T07 | Worker/verifier file → runner digest/spool → authenticated bounded upload → VPS-B bytes and metadata → exact input to reviewer → authorized download | WP-15 produces an evidence file before M3 download tests. WP-18 enables reviewed non-code outputs through the same seam. |
| T08 | Existing runner records → reconcile endpoint and Store → replay or proven stop → new claim only if permitted; read-only GitHub inspection on ambiguous publication | WP-05 provides durable grant/event positions; WP-11 produces outcome resolution; WP-19 allows only read-only reconciliation jobs during restore drain. |
| T09 | Browser/Serve → authorized view → Store committed events → SSE cursor or immutable download | WP-09 qualifies identity forwarding. WP-15 produces ready file; WP-16 wires endpoints and live views; WP-17 exercises real devices. |
| T10 | Hermes/runbook → local maintenance CLI → Store cleanup hold → DB dump + artifact bundle → restore drain → T08 | WP-19 produces backup/restore and drain controls. WP-20 consumes the restored-state and saturation tests as release evidence. |

## 6. Coverage & Traceability Matrix

### Scope coverage

| D2 §1 item | Packages | Acceptance evidence |
| --- | --- | --- |
| S01 | WP-01–02, WP-07, WP-09 | Locked installation, host/auth setup and qualified profiles |
| S02 | WP-03–04, WP-08, WP-10, WP-13–14 | Supplied/committed specs, guide/repo intake and one-/multi-package receipts |
| S03 | WP-03, WP-05, WP-08, WP-11, WP-14, WP-19 | Persisted grant/events, confirmed recovery and no unauthorized retry |
| S04 | WP-04, WP-07, WP-09, WP-13–14 | Versioned roles, fixed tier behavior, independent frontier seat proof |
| S05 | WP-06–11, WP-14 | Actual verification, separate refs, reviewed integration, PR confirmation |
| S06 | WP-07, WP-11–12, WP-14 | Same RPC attempt across debug turns, verified fix with PR |
| S07 | WP-04, WP-09, WP-15–17 | Private server-rendering, two browsers, actions, SSE, file evidence |
| S08 | WP-15, WP-18, WP-20 | All three workflows tested, live marketing and grant files reviewed |
| S09 | WP-02, WP-09, WP-14, WP-17, WP-19–20 | Saturation, operations, recovery and release qualification |

### Module and state ownership coverage

| D2 §8 module or functional block | Introduced/wired | Completed or exercised by |
| --- | --- | --- |
| bootstrap, contracts, config | WP-01, WP-04 | WP-05, WP-08–09, WP-15–16, WP-19 |
| HTTP and operator actions/read/SSE | WP-04 | WP-05, WP-11, WP-13, WP-15–17, WP-19 |
| Control and pure Workflows decisions | WP-04, WP-08 | WP-10–13, WP-15–16, WP-18–19 |
| Store and migrations | WP-03 | WP-05, WP-08, WP-10–11, WP-15–16, WP-19 |
| Artifacts | WP-15 | WP-16–20 |
| Runner placement, journal, exchange and commands | WP-05, WP-08 | WP-11–12, WP-15, WP-18–19 |
| Execution and role/profile input | WP-04, WP-07–09 | WP-12–14, WP-15, WP-18 |
| Repository workspace, publisher and file operations | WP-06, WP-08 | WP-10–12, WP-15, WP-18–19 |

## 7. Completion Criteria

| D2 §14 criterion | Release evidence required |
| --- | --- |
| A1 | Real phase of at least five packages reaches a reviewed PR without intervention. All acceptance evidence is present and target merge remains with operator. |
| A2 | Live control restart and prolonged runner disconnect retain the same attempt, then replay through recovery. Show positive interruption and unknown-before-abandon paths. |
| A3 | Two real pi attempts overlap across isolated worktrees/refs. Serialized integration preserves evidence and remote state. |
| A4 | Real debug task produces multiple turns on the same pi attempt and a verified PR without a final operator stop. |
| A5 | One live marketing run and one grant run each deliver usable reviewed files. Business-development workflow passes integration. |
| A6 | Private browser control works on MyPC and Chromebook, including recovered logs, interview/steer and download. No frontend build or client installation. |
| A7 | Operator can audit pinned CLI qualifications, distinct debate seats, real permission isolation, saturation, nightly backup and restore, and release tags. |

The v1 release is complete when all 20 work packages meet their acceptance checks, traces have no unresolved contract gap, and all A1–A7 evidence applies to the final build. Live evidence includes the relevant identities and pinned software versions. No external precondition is waived by a test fixture.

## Revision History

| Version | Date | Changes |
| --- | --- | --- |
| 0.1.0 | 2026-11-19 | Initial roadmap for the v0.1.0 design and v0.1.1 technical specification. |

Review this roadmap. I will revise on request.
