# ADR 0011: Install native apps, then use their native logins

- Status: accepted implementation direction; intended-host verification pending
- Date: 2026-11-20
- Authority: operator correction: install Claude Code, Codex CLI, Antigravity and
  pi, remind the operator to log in to those installs, and execute through them.
- Supersedes: ADR 0010's externally supplied measured-profile prerequisite;
  ADR 0009's requirement that an operator separately build the execution image.
  Container/session/publication boundaries remain in effect.

## Context and decision

The installer wrongly asked the operator to bring an image and capabilities
file. That shifted necessary implementation work to the operator and did not
satisfy the requested install-and-login workflow.

The worker installer builds the supplied native image recipe. It installs the
actual native apps from official distributions, records exact resolved versions
and executable digests, and pins the resulting image ID. It then opens those
same apps for native login under their isolated persistent native-state domains.
There is no SDK replacement, invented authentication, credential copying, API-key
fallback or login under a different installation. Renewal writes remain in place.

Claude/Codex/pi use official npm distributions; Antigravity uses its official
platform manifest and SHA-512-verified native artifact. Build dependencies and
Node are installed in the image. Package fetch retries are disabled where
controllable; vendor/internal retry behavior is not asserted to be fully known.
The image build has a 30-minute outer budget. It contains no login state.

Antigravity receives a dedicated in-container Secret Service using dbus and
GNOME Keyring. The private keyring domain is persistent alongside its native
state. No host bus/socket/keyring is mounted. The domain keyring uses an empty
unlock password for unattended reuse; its host directory is private to the
runner. This protects namespace/ownership boundaries, not encryption against
host administrators. These OS runtime helpers fall under ADR 0009's operator
exception; no new Cursus Python dependency is introduced.

Installed help and bounded native JSON/RPC checks generate capabilities.toml;
it is output, never an input the operator must author. The operator authorizes
a finite invocation/time/charge budget before checks. Native internal provider
requests and billing are not enforceable by a process timeout. A native process
failure or timeout stops setup without automatic inference retries. New
containers verify login persistence; raw login state/output is not exported.
The generator records `native-checked`, distinct from historical manual
`qualified` attestations: these checks establish login/protocol persistence,
not full intended-host resource isolation, maximum-concurrency token refresh or
M3 acceptance. `credential_concurrency` records the number of independently
registered native domains; provider capacity/renewal qualification remains in
WP-17. No silent concurrency reduction is introduced.

Executable repository customization directories are masked in generated native
sessions; textual top-level AGENTS.md remains available. Explicit native flags
and a read-only workspace constrain organization roles. Unknown required flags
fail visibly instead of asking the operator to invent a profile. Existing
qualified images/configs remain supported with the optional new switches off.

A generated pairing code transfers only non-secret deployment metadata from A
to B: image/profile/role settings, repository/capacity settings, runner UUID and
bearer digest. B derives its pinned role release from this generated output;
no native credentials, bearer token or publisher token cross hosts in that code.

## Consequences and acceptance

Keep the single installer and quick-install-first README. Start A first, sign
in to each app as prompted, then pair B using installer output. Account login
requires operator participation; install does not impersonate the operator.
Code tests must cover all four installations, native login command routing,
profile contracts, pairing limits, RPC stdin lifetime, native AGY event parsing,
private keyring startup and customization masks. Local fixtures and offline help
inspection must not be reported as successful real logins/provider checks.

Official references:
- [Claude installation](https://code.claude.com/docs/en/setup),
  [native login and CLI flags](https://code.claude.com/docs/en/cli-reference).
- [Codex CLI](https://developers.openai.com/codex/cli),
  [CLI reference](https://learn.chatgpt.com/docs/cli/reference).
- [Antigravity install](https://antigravity.google/docs/getting-started?tab=cli),
  [native login](https://antigravity.google/docs/install),
  [stream protocol](https://antigravity.google/docs/cli/headless).
- [pi installation and /login](https://upd.dev/badlogic/pi-mono/src/branch/main/packages/coding-agent/README.md).
