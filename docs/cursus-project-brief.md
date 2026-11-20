# Project brief: Cursus

> **Partly superseded (2026-11-20, [ADR 0016](decisions/0016-host-native-single-host.md)).** Cursus
> now runs your already-installed, already-signed-in CLIs directly on one host, in one process, with
> no isolation. For the system as built read [architecture.md](architecture.md); for installation and
> operation read the [README](../README.md) and [runbook](../ops/runbook.md). The two-VPS topology,
> host-account execution and per-CLI service accounts described below are superseded; the goals, the
> four CLIs, the evidence gates and the private pull-request workflow remain.


**Date** 2026-11-19  
**Status** Approved  
**Author** @Dan

Build a small orchestrator of our own that turns one spec into a finished project phase. The output is reviewed pull requests, or non-code deliverables. Cheap pi workers do the work; frontier models only plan and review.

Name: Cursus. Brief version 1.2.1.

## Goal and operator contract

Normal execution has two required operator touchpoints: write the spec and judge the result. Decomposition, implementation, verification, and internal review run autonomously. The operator can take part in interviews, steer work, and resolve exceptional parked outcomes.

- **Unit of delegation:** anything from a yolo oneshot to a project phase made of many work packages to a single ticket.
- **Debugging sessions:** iterative work, which does not fit a fixed build-review-merge pipeline. A successful session ends autonomously with a verified fix and a PR.
- **Non-coding work:** any workflow can be added as an extension, with or without a GUI. Marketing, grant applications and business development/planning ship with the first release. Their output is reviewed deliverables (documents, drafts) ready for the operator to use. Publication, submission, and outreach are outside Cursus's authority.
- **Control surface:** steering happens from MyPC or the Chromebook, so it must be reachable in a browser.

## Hard constraints

**Tier model.** This is the operator's design and is not open for redesign.

- **Production tier.** All production labor runs on `deepseek-v4.1-flash`` `via OpenCode Go `(keep provider, model and reasoning effort adjustable)`, executed by **pi**. Volume is effectively unlimited, up to about 1 billion tokens per month.
- **Frontier tier.** Frontier subscriptions do organizational labor only: architecture, specs, decomposition, plans, review, judgment.
- **No arbitration machinery.** No quota-aware routing, failover, rotation or spend-based dispatch. A frontier tier running dry is a misallocation of work, not a routing problem. Spend tracking is observability at most.

**Providers and invocation.**

- **Claude:** only as the `claude` binary invoked directly, for architecture, planning, review and judgement. Never for coding, never as a model inside pi or any other harness.
- **OpenAI:** `codex exec` (non-interactive) for architecture, planning, review and judgement.
- **Google:** `agy -p` (Antigravity) is mandatory, for architecture, planning, review and judgement.
- **Direct calls only.** All agent CLIs are called directly: no meta-harness, no adapter layer.
- **No OpenRouter** anywhere in the development path.

**Dependencies.** Permissive licenses only, actively maintained, and few of them.

## Topology

All agentic work runs on the two VPS. The machines are joined by a Tailscale tailnet, and nothing is exposed to the public internet. GitHub (`playa77`) is the hub for repos and PR review. Cursus operates only on trusted repositories owned or approved by the operator. It may push work branches, integrate accepted packages on integration branches, and open PRs. The operator alone merges into the target branch.

| Machine | Role | Runs |
| --- | --- | --- |
| VPS-B (4 vCores, 8 GB) | Control plane | Orchestrator, coordination state, web control surface; stays responsive while workers are saturated |
| VPS-A (6 vCores, 12 GB) | Workers | pi workers, frontier CLIs, worktrees, builds and tests |
| MyPC | Client, optional second worker later | Browser, SSH |
| MyChromebook | Client only | Browser |

## Transport between sessions

Sessions never talk to each other directly. The orchestrator is the only hub: every prompt goes out from it, every answer comes back to it, and each exchange is stored in the coordination record. "Direct calls" means no adapter layer between the orchestrator and a CLI. It does not mean sessions messaging each other.

- **Runner per worker machine.** A small runner process on VPS-A (later MyPC) pulls jobs over the tailnet, starts the CLI locally and streams its events back. Pulling, rather than VPS-B pushing over SSH, keeps running sessions alive through orchestrator restarts and dropped connections.
- **Structured output from every CLI.** The flags below are to be confirmed in M1:
  - pi: `--mode json` for one run, `--mode rpc` (JSONL over stdin/stdout) for a long session;
  - Claude: `claude -p --output-format stream-json`;
  - Codex: `codex exec --json`;
  - Antigravity: `agy -p --output-format json`.

  The runner converts all of them into one event format.
- **Hand-offs.** When one session's output feeds another (worker to reviewer; advocate to devil's advocate to judge), the orchestrator puts the earlier outputs into the next session's prompt or into files in its worktree.
- **Artifacts by reference.** Code travels by git: worktree branches are pushed, and messages carry branch names and commit SHAs. Documents travel as files in the repo or the store.
- **Consequence for the store.** Worker events are frequent and small, so the store needs a real message path (e.g. PostgreSQL with LISTEN/NOTIFY). GitHub Issues can mirror the human-visible state, but cannot be the message bus.

## What the system must do

1. **Intake.** Accept a spec (coding phase, debugging session, business idea, marketing or grant task) from the browser surface or a file in a repo. Or else interview the user in a guided and structured manner, until a spec can be generated with full confidence.
2. **Decompose.** A frontier CLI turns the spec into a phase plan: ordered work packages, dependencies, typed acceptance criteria per package.
3. **Adversarial review (optional).** Before execution, a phase plan can go through a structured debate between the three frontier models: an advocate defends it, a devil's advocate attacks it, a judge rules and lists required changes. This runs for several rounds, until the judge accepts or a round limit is hit. The same protocol can run on a spec, with the operator answering questions between rounds, interview style.
4. **Coordinate.** Keep one durable record of the shared state: who owns what, what has been tried, what changed, what merges next. With unlimited cheap parallelism, this is the real bottleneck.
5. **Dispatch.** Start pi workers on VPS-A, one isolated git worktree per package. Each worker gets a role-specific tool set (e.g. read-only scouts, `--tools` allowlists) and its delegation wired from outside pi.
6. **Verify.** A package passes only on evidence: tests run, acceptance criteria checked, completion explicitly reported. The worker's own claim is never enough.
7. **Review.** An independent session (frontier CLI or a separate pi reviewer) checks each result against its criteria. It sends failures back with a bounded number of rounds, then parks them.
8. **Assemble.** Integrate passing packages and open the PR(s) for the operator. Non-coding phases deliver documents instead.
9. **Sequence.** When one package or slice completes, activate the next, until the phase is done. No human in between.
10. **Observe.** The browser surface shows phase progress, live worker logs and parked items, and accepts steering. Spend is shown, never acted on.
11. **Manage roles.** A role registry defines every role (e.g. interviewer, planner, decomposer, scout, worker, tester, reviewer, advocate, devil's advocate, judge). For each it sets the model and CLI, tool set, prompt and limits. The tier rules are enforced there: frontier roles never write code, production roles run only on pi.

## Scope

**In v1:** the eleven functions above, for a single operator, on the topology above, with pi and the three frontier CLIs.

**Out of v1:**

- multi-user access;
- public exposure;
- quota or spend-based routing;
- a plugin system;
- a desktop or mobile app;
- any model or provider abstraction layer.

**Size budget.**

- **Hard ceiling:** 5% of Fusion (about 100k lines).
- **v1 target:** a small fraction of that. Every module must trace to one of the eleven functions.
- **Watch item:** unrequested scope is the defect to watch for, more than raw line count.

**Engineering rules.**

- Python, with thorough comments and error handling.
- Complete files only.
- Under 500 lines per file is the norm; over 1,000 is a refactor signal.
- American English.
- SemVer and a changelog from the first commit.
- Few, permissive dependencies.

## Success criteria for v1

All five must hold on real work, not demos:

- [ ] One real coding phase of at least five work packages goes from spec to PR(s) with zero operator intervention.
- [ ] The orchestrator survives a restart mid-phase with no lost or corrupted state, and resumes where it stopped. A runner disconnect spanning multiple missed heartbeats leaves package ownership intact and creates no duplicate attempt. On reconnection the original attempt is reconciled and its events are replayed.
- [ ] Parallel pi workers never collide on files, branches or merges.
- [ ] A debugging session runs iteratively to a fix without being forced into a ticket shape.
- [ ] One marketing task and one grant application produce usable deliverables.

## Milestones

Each milestone ends usable on its own and is tagged as a release.

1. **M0 – Infrastructure.**
   - Tailnet across all four machines.
   - All CLIs authenticated non-interactively on VPS-A, each under its own user, with token lifetimes and renewal recorded.
   - Repo created and versioned.
2. **M1 – One package end to end.** Spec → one work package → pi worker in a worktree → verification → independent review → PR. Run from the command line. Role registry and the runner on VPS-A in place from the start.
3. **M2 – Phases.** Decomposition into many packages, durable coordination state, parallel workers, automatic sequencing, restart safety. Optional adversarial review of phase plans, and of specs in interview style.
4. **M3 – Control surface.** Browser view of phases, workers, logs and parked items, with steering. Reachable over the tailnet only.
5. **M4 – Non-coding pipelines.** Extension mechanism for workflows (with or without a GUI). Marketing, grant applications and business development/planning ship as the first extensions, producing deliverables on the same core.
6. **M5 – Second worker.** MyPC joins as an optional worker; work is routed per machine.

## Decisions

All decided on 2026-11-19. Items marked "Confirm in M1" are CLI or platform details to verify in a short spike before building on them.

### Coordination state store: PostgreSQL on VPS-B

- **One database, one writer.** Only the orchestrator talks to it; runners and the UI go through the orchestrator's API.
- **Append-only event log plus current-state tables.**
  - The event table holds every prompt, answer and state transition, with an idempotency key.
  - State tables cover phases, work packages, attempts, current ownership, and runner liveness.
- **Job queue in the same database.** `SELECT ... FOR UPDATE SKIP LOCKED` for claiming work; `LISTEN/NOTIFY` to wake the orchestrator. No separate queue broker.
- **Durable attempt ownership.** Each claim records the owning runner and attempt. Heartbeats report runner liveness. Missed heartbeats mark the runner unreachable and leave the claim in place. Elapsed time never releases a claim or requeues work.
- **Reconciliation.** After a disconnect or orchestrator restart, reconcile the existing attempt using the runner's durable local record and event spool. A running attempt continues under its original ownership. A recorded completion enters normal verification. A confirmed interruption or cancellation releases the claim. Any retry permitted by the workflow starts in a fresh worktree.
- **Unknown outcome.** When the original attempt cannot be recovered and its outcome cannot be established, park it with ownership intact. An explicit operator abandonment action records the decision before Cursus can authorize a replacement. A late report from an abandoned attempt cannot change the replacement's state or be accepted for integration.
- **Migrations and backups.** Migrations are numbered plain SQL files in the repo. A nightly `pg_dump` runs as a Hermes cron job.
- **Driver:** `asyncpg` (Apache-2.0) rather than psycopg (LGPL).
- **GitHub** holds only branches and PRs, optionally one tracking issue per phase for visibility.

**Why.** It is the only option with transactional claiming, a message path and restart safety in one component. GitHub Issues is too slow and too coarse for worker events; files in git have no safe concurrent claiming.

### Worker control channel: pi `--mode rpc`, one process per attempt

- **Long sessions.** Each work-package attempt gets a fresh pi process in RPC mode (JSONL over stdin/stdout), owned by the runner. Steering messages, aborts and the final completion report all go over that pipe.
- **One-shot roles** (e.g. a scout query) use `--mode json`.
- **Fresh process per attempt:** no state leaks between attempts, and a crash affects one package.

**Why.** RPC gives structured events plus mid-session steering, which debugging sessions need. The pi SDK would tie the orchestrator to Node/TypeScript while it is written in Python.

**Confirm in M1:** the RPC message types for steering, abort and session end.

### Delegation inside pi: wired by the orchestrator, no in-session sub-agents in v1

Every delegation is a work package or an attempt the orchestrator creates. Workers never start their own sub-agents.

**Why.** Coordination is the stated bottleneck. Sub-agents started inside a pi session are invisible to the coordination store: nothing records who owns what or what was tried. `pi-subagents` is also a single-author dependency.

**Revisit after M2** only if workers keep needing quick read-only reconnaissance mid-task.

### Frontier reviewer: fixed assignment per role, always read-only

Defaults, all changeable in the role registry:

| Role | Default CLI |
| --- | --- |
| Spec interviewer, planner, decomposer | `claude -p` |
| Package reviewer (code and deliverables) | `codex exec` |
| Adversarial review | One seat per model (see that protocol) |

- **Fixed by role, never chosen at run time.** No routing by load or quota, consistent with the tier model.
- **Reviewers cannot edit:**
  - Codex runs in its read-only sandbox.
  - Claude runs in its plan or permission-restricted mode.
  - Antigravity runs without auto-approve.
- **A reviewer never reviews its own output.**

**Confirm in M1:** the exact read-only flags of each CLI.

### Transport between machines: pull-based runner over the tailnet

- **A systemd service per worker machine.** It has its own bearer token and talks HTTP to the orchestrator over the tailnet (WireGuard-encrypted, never public).
- **Claim, heartbeat, report.**
  - Claim by long-poll (`GET /jobs/next`), which returns a job and its durable attempt claim.
  - Heartbeats report runner liveness. Claims remain in force while the runner is unreachable.
  - Events are sent in batches (`POST /attempts/{id}/events`), each with an idempotency key.
- **Local spool.** Every event is first appended to a local JSONL spool. If the orchestrator is down, the runner keeps working and replays the spool on reconnection. Cursus deduplicates replayed events by key and reconciles the existing claims before dispatching any replacement attempts.
- **Git.** Workers push attempt-specific work branches to GitHub under the package prefix (`wp/<phase>/<package>/`). An abandoned attempt cannot overwrite a replacement's branch. Integration branches become the PRs.

**Why.** Running sessions survive orchestrator restarts and dropped links. SSH exec from VPS-B would tie every session's life to one SSH connection.

### Role registry format: one versioned TOML file, prompts as Markdown

- **`roles.toml` in the orchestrator repo.** Each role sets tier, model, CLI, tool allowlist, limits and a prompt file path. It carries a `schema_version`.
- **Prompts** live as `prompts/<role>.md`, so changes diff cleanly in git.
- **Validated at startup:**
  - frontier-tier roles may only use `claude`, `codex` or `agy`, with no write tools;
  - production-tier roles may only use pi.

  The orchestrator refuses to start on a violation.
- **Traceability.** Every attempt stores the registry's git hash, so any result can be traced to the exact role definitions that produced it.

**Why.** Python reads TOML from the standard library (no dependency). Config in git gets versioning and review for free; rows in the database would not.

### Adversarial review protocol: author defends, two other models attack and judge

- **Seats.** The model that wrote the plan is the advocate. The other two take devil's advocate and judge, with a configurable default. The judge is never the author.
- **Round structure:**
  1. The advocate states the plan and its rationale.
  2. The devil's advocate writes numbered objections, each with severity, evidence and a proposed fix. This is a blind first pass: it does not see the advocate's rebuttals.
  3. The advocate answers each objection: concede, rebut or amend.
  4. The judge rules on each objection (upheld or rejected) and lists the required amendments.
  5. The author revises the plan.

  Later rounds cover only upheld objections and new issues raised by the amendments.
- **Stop rule.** The judge returns accept, or a round produces no upheld blocker. The hard cap is 3 rounds. At the cap, the plan is parked for the operator with the full transcript; this is an escalation, not a gate.
- **Output.** Each verdict is a JSON document (objection ids, rulings, amendments, verdict), stored in the event log.
- **Fresh sessions every round**, with no shared memory between seats.
- **Spec mode.** The judge's open questions go to the operator through the interview flow. The answers are added to the spec before the next round.

### Control surface stack: server-rendered pages, no build step

- **Stack.** FastAPI (MIT) on uvicorn (BSD), Jinja2 templates (BSD), htmx (BSD) for interaction, and Server-Sent Events for live worker logs. No Node toolchain and no separate front-end build.
- **Network.** It is served on VPS-B on localhost only and published on the tailnet with `tailscale serve` (HTTPS).
- **Login.** Tailscale's identity headers plus an allowlist with your account, so there is no separate login.
- **Browser delivery.** The operator opens a private tailnet address in an existing browser on MyPC or the Chromebook. The frontend is server-rendered, with no installed client, React bundle, or frontend build step. A separate Hermes design pass uses Proper UI as a read-only reference catalog and produces the visual handoff for operator approval. Architecture and technical specifications define browser behavior, permissions, and contracts. The design catalog and its connector are external to the deployed project.

**Why.** It needs the fewest dependencies and works in any browser. It also keeps the whole system in one language and one deployable.

**Confirm in M1:** that Tailscale Serve passes the identity headers as expected.

### Project name: Cursus

Named after the *cursus publicus*, the Roman relay network that carried messages between stations. Cursus does the same: a hub relaying work between its stations.

## Prior art worth borrowing

Ideas only, no code or dependencies:

- **Fusion:** Mission → Milestone → Slice → Feature → Task hierarchy; typed acceptance criteria checked by a validator; the next slice activates when the current one completes.
- **ordewell:** a task passes only when it explicitly reports completion; the exit code is supporting evidence, never the verdict.
- **Orbi:** an independent review session checks each PR against the acceptance criteria; repair rounds are bounded, then the item is parked for a human.
- **Kandev:** a different agent per workflow step (plan, implement, review).
- **r/LocalLLM field report (OpenHands user):** pi over ACP with GitHub Issues as source of truth and Scout/Worker/Tester/Reviewer roles. The author abandoned a self-built orchestrator after a week of edge cases. That is the main risk this project must design against.

## Revision History

| Version | Date | Changes |
| --- | --- | --- |
| 1.2.1 | 2026-11-19 | Replaced ReUI with a separate Hermes design pass using Proper UI references. The output is an operator-approved handoff for the existing browser stack. |
| 1.2.0 | 2026-11-19 | Replaced lease-expiry requeue with durable ownership and outcome reconciliation. Recorded trusted-repository scope, PR merge authority, debugging and non-coding completion boundaries, and the browser-only ReUI handoff. |
