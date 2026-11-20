> **Obsolete (ADR 0016):** describes the removed 0.6.0 container/two-host design. Rewritten in work package D.

# Container execution acceptance

Baseline: clean main `38ea8ed`; PR #6 open/unmerged `20831cf`, explicitly rejected.
ADR 0009 records the accepted direction. This matrix is a checklist, not evidence
of completion. Fixture, local runtime and intended-host/provider evidence must
remain separately identified. Live qualification stays deferred to M3 end.

| Rejected finding | Required acceptance check |
| --- | --- |
| 1 Capacity erosion | Inspect same-boot surviving container; unknown holds reservation; later confirmed stop/removal restores productivity without relaunch. |
| 2 Residue | Disposable root/HOME/tmp removed; only explicit auth state persists; peer workspace/cache and host temporary storage are not mounted. |
| 3 Identity | Intent name/token before create, immutable ID before start; recovery targets actual container/descendants and rejects name/ID/token collisions. |
| 4 Exception leaks | Inject prepare/create/start/exec/stop/remove faults; durable cleanup retries after terminal workflow result; never reuse uncertain reservations/domains. |
| 5 Recovered claims | Never-started claim waits locally and is reconsidered after resource release without reconnect or a new claim. |
| 6 Progress | Waiting debug plus competing production leaves verifier room; oldest pending claims and rotating lanes make progress; independent provider ceilings. |
| 7 Credentials | No copying; disjoint explicit auth domains, persisted renewal, exclusive ownership through cleanup, startup rejects insufficient qualified concurrency. Provider renewal remains unqualified locally. |
| 8 Identity/mounts | Non-root numeric identity and keep-id mapping pinned; host ownership validated; paths cannot overlap state/cache/secrets/peers; runtime authority never mounted. |
| 9 Visibility | Preparing/running/stopping/cleanup/uncertain/removed with reason, since, resource/domain usage and retry status in runner health/operator view. Abandon is not reclamation. |
| 10 Evidence | Controlled runtime state machine plus real fixture subprocess protocol tests; eventual recovery as well as no-premature-reuse. Actual runtime/host qualification separately recorded. |
| 11 Roles | Extra production role executes through its qualified transport/tool contract without name-specific mode or identity. |
| 12 History | Indexed active journal projections and bounded replay work per tick; retired history not repeatedly scanned; heartbeat independent of replay. |
| 13 Setup | Both host dry-runs, incompatible config rejection, immutable stage, explicit drain/activation/rollback boundary; aggregate admission and service resource limits agree. |
| 14 Containment | Malformed frame/session exception fails only that session; runtime stop still occurs; failed heartbeat/log supervisor terminates intake visibly. |

Preserve all existing workflow, artifact, publication and browser checks. Installation
artifacts must pass offline syntax/config/package checks. Record actual commands,
failures and limitations in tests/qualification.md; no live readiness claim.

## Disposition and evidence

Source implementation is proposed for review, not accepted by the existence of a
branch or this checklist. PR #6 remains rejected. Actual host/provider gates below
remain open until the deferred M3-end qualification. The operator separately
approved OS runtime helpers; Cursus libraries remain permissive (ADR 0009).

| Finding | Source disposition / controlled evidence | Remaining qualification |
| --- | --- | --- |
| 1 | `ContainerTests.test_same_boot_uncertainty_surviving_process_then_productivity`: real surviving fixture process, retained reservation, restart and eventual reclamation. | Real Podman same-boot/host restart. |
| 2 | Disposable root/HOME/tmp, explicit mounts, acknowledged workspace cleanup; connected lifecycle fixture deletes read-only snapshots. | Actual namespace/peer/mount residue probes. |
| 3 | Intent and immutable ID journal/ledger, host UID/GID/image checks; collision and missing-ledger tests. | Runtime identity/descendant probes on VPS-A. |
| 4 | Create/remove fault and idempotent retry tests; result delivery separate from cleanup; exact unknown-final receipt ordering test. | Intended-filesystem power-loss/stop behavior. |
| 5 | `PendingClaimTests`: actual held claim resumes through runner service after resources return, same attempt, no reconnect. | Host pressure behavior. |
| 6 | Separate provider claim test (six claims), all-lanes admission test (four pi plus six frontier sessions and one verifier), actual memory/disk pressure tests (ADR 0014), five continuing debug cases with competing reservations. | Actual cgroup enforcement/maximum-load sizing; no simultaneous-max promise. |
| 7 | No copies; exclusive explicit domains; invalid overlap and incomplete capability rejection. | Native provider concurrent renewal/persistence/recovery remains unqualified; startup requires attestation at requested ceiling. |
| 8 | Rootless keep-id/non-root command contract, ownership and image checks; prohibited mount tests. | Actual UID/userns/mount/cgroup effects. |
| 9 | Browser/health lifecycle and waiting/cleanup reasons with timestamps; durable cleanup backlog. | Fresh intended-host readiness/diagnostic walkthrough. |
| 10 | Same-UID fixtures explicitly labeled; real surviving-process and eventual-productivity assertions; connected workflow and wheel checks. | Actual container boundaries are not asserted from fixtures. |
| 11 | `SessionContainmentTests`: extra qualified `artisan` coding role uses RPC without name-specific identity/mode; malformed peer fails independently. | Native role tool enforcement. |
| 12 | 200 retired requests compact to bounded unresolved inventory, reopen retains uncertain launch; bounded replay and SQL usage aggregation. | Intended-disk/history-scale measurements. |
| 13 | Both dry-runs, strict supplied-config rejection, constructor/config tests; durable drain stops claims; immutable releases and migration rollback guard. | No setup script was applied; systemd/upgrade/rollback on hosts unqualified. |
| 14 | Malformed peer with real subprocess, all debug fault/cancel cases, supervised main/background tasks. | Host runtime failures and service restarts. |
