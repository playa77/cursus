# ADR 0014: Session ceilings with shared execution resource pools

- Status: superseded by [ADR 0016](0016-host-native-single-host.md) (shared cgroup pools); ceilings and pressure guards retained
- Date: 2026-11-20
- Authority: operator selected “use the session ceilings and shared host safeguards” after reporting that installer defaults admitted only one agent.
- Supersedes: ADR 0009's per-container maximum reservation admission rule and ADR 0012's equal agent/verifier split suggestions. Container isolation, verifier resource separation and credential-domain leases remain.

## Context

The scheduler summed each container's maximum RAM/CPU/tasks before admission.
Installer suggestions assigned half the total to each agent and half to the
verifier, making the configured worker/provider ceilings unreachable.

## Decision

Worker (1–4) and independent Claude/Codex/Antigravity (1–2 each) ceilings are the
fixed agent concurrency limits. Do not reserve or sum per-container maxima to
admit sessions. Actual host memory below the host reserve or disk below the free
space floor can delay starts. Keep aggregate cgroup RAM/CPU/task enforcement and
separate agents/verifier slices. Agents share their slice; individual maximum
limits remain upper bounds, not allocations or admission reservations.

Guided setup derives agent maximums from the entire agents pool instead of
asking for individual partitions. Reserve one eighth of execution RAM (capped
at 1024 MiB), one fifth of execution CPU (capped at 1000 units), and 1024 tasks
for the verifier, bounded for small budgets. The remaining pool is shared by all
agents. Suggest 1024 total tasks per selected session slot plus the verifier.
Explain shared limits and memory pressure without claiming measured capacity.
Preserve saved configurations and existing individual limits; their maxima no
longer consume admission slots. No automatic rewrite or trust change.

Native onboarding commands start from their runner-owned setup directory,
including recovery/probes, rather than inheriting an operator's private home.

## Rationale and consequences

Shared enforcement matches the selected policy and permits idle CLI sessions
to coexist without reserving peak build resources. Retaining per-container
reservations with smaller limits was rejected by the operator. Removing all
host safeguards was not selected. Under load, CPU contention can slow sessions
and exhausting a cgroup memory/task limit can fail work; counts are not a
performance or simultaneous-peak-memory guarantee. Verifier isolation remains.
Changing runtime admission applies to existing configurations on upgrade.

Acceptance: admit four pi and two of each frontier CLI plus one verifier with
oversubscribed maximums; reject extra lane sessions and reused credential domains;
preserve actual memory/disk pressure checks, cgroup slice placement and bounded
container limits; installer suggestions do not introduce an agent-count ceiling;
child processes use the runner-owned directory. No live inference required.
