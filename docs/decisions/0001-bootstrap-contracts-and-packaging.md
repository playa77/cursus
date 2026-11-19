# ADR 0001: M0 package and contract boundary

- Status: accepted for WP-01
- Date: 2026-11-19
- Basis: [D2 §§2–5.1, 8.1, 13](../cursus-technical-specification-v0.1.2.md), [WP-01](../cursus-implementation-roadmap-v0.1.1.md#wp-01--bootstrap-contracts-and-python-package--m0)

## Context

The repository starts with specifications only. Later services need one installed
package and strict shared validation without introducing runtime service behavior
in M0. D1 R11 requires permissive dependencies and a small Python implementation.

## Decision

Use a src-layout package, SemVer 0.1.0, the standard build frontend and pinned
flit_core backend. Lock the four prescribed runtime dependencies, their mandatory
closure and build tools with release artifact SHA-256 hashes. License evidence is
in [dependency-licenses.md](../dependency-licenses.md). Setuptools was considered
and rejected after inspection found bundled LGPL and MPL components.

Contracts return detached JSON-compatible values or raise `Problem`, whose safe
`as_dict()` representation is the shared error payload. Introduce scalars, Repo,
FileRef, Candidate, Input and Action now; fail closed on future contract names.
No stateful authorization is implied by lexical validation. Later WPs extend the
closed validator registry with their concrete producer/consumer contracts.

Require union `kind`, reject unknown/inapplicable fields and JSON duplicate keys,
and hash validated values using the D2 canonical JSON encoding. Git object format
is explicit validation context (`sha1` default, `sha256` by enrollment). Code form
alone defaults to `phase` as specified. No other missing union data is inferred.

Keep ref validation stateless on both hosts by implementing the documented
`git-check-ref-format` branch rules and comparing accepted/rejected examples with
real Git in unit tests. Repository operations must still enforce enrollment,
ref ownership and Git validation at the actual Git boundary in WP-06. No Git or
agent process is started by the control-side contracts module.

## Consequences

Help/version work without credentials or a database. M0 exposes no stub runtime
commands. The lock includes artifact hashes for other Python/platform builds,
but only the locally tested interpreter is qualification evidence. Runtime
cross-entity checks and process-specific settings remain in their assigned WPs.
A separate schema/validation dependency was considered unnecessary for these
small shared primitives; HTTP framework dependencies stay unused until WP-04.
