# ADR 0013: Installation does not enroll a repository

- Status: accepted for implementation; intended-host verification pending
- Date: 2026-11-20
- Authority: operator correction that a fresh installation may remain unused for
  two weeks, followed by a request to open a PR implementing that correction.
- Supplements: [ADR 0011](0011-native-install-and-login.md) and
  [ADR 0012](0012-discovered-installer-inputs.md).

## Context

Guided installation asks for a repository, target branch, verification command
and GitHub publisher token before any work is requested. These are repository
enrollment decisions. Existing configuration and admission already support an
empty repository list and reject unenrolled work.

## Decision and approaches

Fresh guided setup saves `repositories = []` on both hosts through the pairing
code. It asks no repository questions and provisions no publisher credentials.
Existing explicit configurations and enrolled-repository credential preparation
remain supported. No dummy repository, placeholder token or automatic enrollment
is introduced. Native login, resource policy and host pairing stay in scope of
installation as before; this change does not redesign those flows.

Making enrollment merely optional would still ask the irrelevant setup question.
A new enrollment service or browser workflow would expand this fix unnecessarily.
Use the existing explicit configuration and guarded reconfiguration workflow to
enroll a repository later; document it precisely.

## Consequences and acceptance

An installed deployment can remain idle indefinitely without GitHub access. This
does not imply native sessions never expire or eliminate ordinary maintenance.
Publisher paths remain reserved in runner configuration for later enrollment,
but their files are neither required nor read while no repositories are enrolled.
Existing enrollments are never removed on installer reruns.
The new-run screen explains empty enrollment instead of presenting an unusable
repository selector; enrolled deployments retain the existing form.

Regression checks cover fresh worker configuration without repository prompts,
empty-list serialization/pairing, absent publisher files without token prompts,
preservation of existing configuration, configuration loading and refusal of
unenrolled work. Actual Ubuntu/systemd/provider qualification remains separate.
