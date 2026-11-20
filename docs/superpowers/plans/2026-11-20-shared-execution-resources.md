# Shared execution resources implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task.

**Goal:** Honor configured session ceilings with shared host safeguards and fix onboarding from a private operator home.
**Architecture:** ADR 0014; retain existing cgroup slices and lifecycle/credential contracts. Remove only admission accounting of container maximums; generate shared-pool defaults.
**Tech stack:** Existing Python, unittest, Podman/systemd; no new dependencies.
**Spec:** docs/decisions/0014-shared-execution-resources.md

## Constraints and review focus

Preserve saved configs, lane ceilings, credential leases, verifier isolation and host reserves. Check ten agent slots, actual pressure, small budgets, prior configuration maxima and child cwd.

## Task 1: Admission and guided defaults

- [x] Add failing all-lanes admission/pressure regressions and replace equal-split installer expectations with shared-pool invariants.
- [x] Remove maximum-reservation arithmetic from Containers.fits; retain lane checks and actual memory/disk pressure gates.
- [x] Derive agent maximums from the shared agents pool, bounded verifier allowance and configured session counts. Explain contention rather than a computed agent ceiling.
- [x] Update affected integration reservation expectations and docs/changelog, explicitly superseding prior policy.
- [x] Run full unit suite and relevant local offline checks; record unrun intended-host checks.

## Task 2: Native working directory

- [x] Reproduce caller cwd inheritance using a real subprocess fixture.
- [x] Set runner-owned cwd for Podman, recovery, systemctl and probe child processes.
- [x] Verify native fixtures and full unit suite; no live provisioning/inference.

## Verification and review

74 unit tests passed in the existing dependency-complete test environment;
10 affected execution integration tests passed against a task-owned disposable
PostgreSQL 18 instance with a private Unix socket and an explicit child environment
allowlist. The database was stopped after tests. Native cwd regression, recovery
and RPC fixtures passed. Shell syntax, dependency and diff checks passed.
Fresh read-only review found no actionable defects. No intended-host provisioning,
real Podman/cgroup enforcement, provider inference or peak-load qualification was
performed. No saved host configuration was rewritten.
