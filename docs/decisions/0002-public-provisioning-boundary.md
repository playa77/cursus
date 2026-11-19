# ADR 0002: Public provisioning templates and private live evidence

- Status: accepted; live M0 qualification deferred
- Date: 2026-11-19
- Basis: [WP-02](../cursus-implementation-roadmap-v0.1.1.md#wp-02--provision-hosts-and-cli-identities--m0), [D2 §§4, 7, 13–14](../cursus-technical-specification-v0.1.2.md)
- Operator direction: during WP-01/02 implementation, the operator clarified
  that host access details are irrelevant to this public GitHub repository.

## Context

WP-02 combines reusable deployment artifacts with live operator-controlled VPS,
tailnet and native-provider enrollment. Public source must not contain secrets
or a private host/device inventory. No live deployment evidence was supplied.

## Decision

Deliver commented TOML templates, a provisioning runbook and an evidence
checklist in source. Use explicit replacement markers for private values and
empty/unqualified capability fields. Record real host inventory, native login
and renewal details, literal smoke commands and sanitized results in a private
operator-local qualification record. Public records may link a non-sensitive
attestation identifier, never require publication of private machine details.

The TOML grouping establishes consistent provisioning names for the later
config loader; M0 only checks TOML syntax and cross-template conventions. Strict
runtime validation starts in WP-04 and profile consumption in WP-07. These files
are not a runnable deployment and do not enable roles. Service units, sockets,
HTTP routes, migrations and agent execution remain in their assigned packages.

## Consequences

Repository work can finish without SSH or credentials. Live WP-02 acceptance
and the M0 tag remain pending until the operator executes the named checks.
WP-03's live predecessor gate is not waived by these templates. Actual private
provisioning is an operator deployment activity outside this public-source task.
An alternative of embedding machine-specific configs/evidence in source was
rejected following the operator's clarification. No remote changes, provider
calls, host-tool installations, ingress changes or release tags are made here.
