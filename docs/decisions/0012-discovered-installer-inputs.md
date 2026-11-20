# ADR 0012: Discover installer facts; ask for deployment choices

- Status: accepted; intended-host verification pending
- Date: 2026-11-20
- Authority: operator instruction in this task: do not ask users to input information the installer can acquire itself.
- Supplements: [ADR 0010](0010-unified-installer.md) and [ADR 0011](0011-native-install-and-login.md).

Resource admission/default sizing is superseded by [ADR 0014](0014-shared-execution-resources.md); per-container maxima no longer reserve admission capacity.

## Context

The worker-first flow asked for an unexplained controller URL even though
Tailscale already exposes machine names through its supported local CLI.
Machine ownership also does not identify the authorized website operator.

## Decision and rationale

Read Tailscale status once per host using the supported JSON CLI, a 15-second
timeout and no retries. Select the controller peer and authorized operator from
discovered candidates by number; do not guess roles from names or grant access
to the machine owner automatically. Stop with enrollment/visibility guidance
when discovery is unavailable. Carry the worker DNS name in non-secret pairing
metadata; support older codes using a numbered peer selection. Verify that a
controller's own DNS name matches the paired origin before saving configuration.
Display locally detected memory, CPU and disk facts alongside resource-policy
questions. Preserve operator choices for workload limits and spending consent.

## Consequences

No additional dependency, Tailscale enrollment, trust grant or network exposure
is introduced. Discovery does not configure Serve or establish HTTPS readiness.
Existing saved host configurations remain explicit and are not overwritten.
Import model/provider choices from documented settings fields within the newly
installed native domains. An in-container reader returns only those fields; no
auth file, complete settings file or developer-agent state is exported. Missing
selections open the native app once for the operator to save a default; failure
stops setup rather than asking for IDs or guessing a model. This performs no
installer inference. Native account login and model choice remain user actions.

Settings references: [Claude](https://code.claude.com/docs/en/settings),
[Codex](https://learn.chatgpt.com/docs/config-file/config-basic),
[Antigravity](https://antigravity.google/docs/settings),
[pi](https://upd.dev/badlogic/pi-mono/src/branch/main/packages/coding-agent/docs/settings.md).

Acceptance: fixture tests for discovery caching/failure, peer selection,
operator selection distinct from machine ownership, worker pairing transfer,
and refusal of wrong-controller pairing. Actual Tailscale/Ubuntu setup remains
an intended-host check, not established by unit fixtures.

## Resource-question correction (2026-11-20)

Operator feedback identified ambiguous shared help for total and per-container
limits and missing suggestions. Guided setup now asks reserves before budgets,
then agent/verifier limits. Each question names its scope, units and effect;
Enter accepts an explained, editable suggestion and malformed/out-of-range input
retries that question. The summary states schedulable agent capacity with the
verifier reserved. This changes guided suggestions, not runtime admission rules
or existing saved configurations.

Heuristics: host RAM reserve starts at 25% (minimum 512 MiB); CPU reserve at one
sixth (minimum 250 milli-cores), clamped to leave usable execution capacity.
Execution memory starts from the smaller of observed available RAM and supported
physical RAM, minus the selected reserve; CPU uses supported capacity minus the
reserve. Honor the existing 12 GiB/six-core configuration contract. Split starting
agent/verifier allowances equally; start with 2048 total tasks. Each disposable
memory-backed directory starts at one eighth of its container RAM, capped at
512 MiB. Disk floor starts at 10% of observed free space, capped at 10 GiB and
strictly below current free space. These are starting policies, not workload
qualification or guaranteed headroom. Session/account ceilings remain explicit
operator choices without defaults.

Prompt guidance: [Command Line Interface Guidelines](https://clig.dev/), especially
clear state, useful defaults and early input validation. No new prompt dependency.
Acceptance: terminal fixtures covering Enter, custom reserves, invalid numbers,
small and larger hosts, aggregate agent/verifier fit and tmpfs memory headroom.
