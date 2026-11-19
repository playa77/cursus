# ADR 0004: M1 single-package execution and publication

- Status: accepted for WP-04–08; M2 extends the admission, scheduling, recovery
  and target-drift decisions in [ADR 0005](0005-m2-state-and-qualification.md) and
  [ADR 0006](0006-m2-debug-and-conversations.md). Live qualification remains deferred.
- Date: 2026-11-19
- Basis: D1 §§3–7; D2 §§4, 7–8, 12, 15; roadmap WP-04–09
- Task: operator request to implement through WP-09; follows ADR 0003

## Context

M1 needs a runnable single-package path without exposing later milestone
features. Model output must never confer repository or command authority.

## Decision

Admit only code with inline/pinned repository input and exactly one package.
Freeze roles, prompt text, registry commit, profile digest and approved checks in
jobs. Call installed CLIs directly under distinct identities with an explicit
child environment; accept only implemented terminal wire shapes. Profile
changes require requalification. Role-specific profile overrides allow a
read-only pi scout/reviewer without inheriting worker tool rights.

The pure workflow validates report/candidate/evidence/review identities. A runner
captures and pushes immutable attempt and staging refs. Verify the staged tree
and enrolled phase commands before creating an integration publication intent.
Commit each intent before a publisher job becomes claimable. Confirm its exact
remote result before the next intent or delivered state. Ref leases protect the
expected old SHA; ancestry checks independently forbid history replacement.
Never push enrolled targets. PR lookup includes all states; ambiguity or an
unexpected closed/merged PR parks the lane without blind creation retries.

Keep M1 scheduling serial, while heartbeats run independently of execution.
Journals record launch intent before effects; a previous launch intent cannot
cause automatic relaunch. Uncertain stop/publication preserves ownership. Full
recovery, cancellation and abandonment are WP-11; target drift parks until M2.

## Consequences

The executable fixture path proves service/transaction/Git/process integration,
not real vendor authorization, read-only tool enforcement or service isolation.
Real capability flags and private host controls remain WP-09 inputs. No browser
surface, provider SDK, live inference, deployment or release tag is added by
local fixture verification. Multi-package scheduling and automatic drift repair
were deliberately deferred to their approved packages.
