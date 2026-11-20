# Cursus

Cursus coordinates coding work: you submit a task, native coding agents work in
isolated containers, separate checks and review inspect the result, and Cursus
opens a pull request for you to merge. A private website shows progress and lets
you download verification evidence. Debug sessions, guided interviews and optional
three-agent debates are also implemented. Non-code delivery is not implemented yet.

**This is the setup guide for version 0.5.0, configuration schema 2, and the
container execution branch.** It uses two Ubuntu Server 26.04 machines. Do not
combine it with the older instructions for root runners or per-agent Linux users.
[ADR 0009](docs/decisions/0009-container-execution.md) explains that change.

**Deployment status:** source implementation is available; installation on the
intended servers, native provider authentication/concurrency and live acceptance
are still unqualified. The setup scripts do not create a ready-to-use agent image
or discover working vendor authentication/permission settings. Those are real
prerequisites, described below. No tested, universal vendor recipe is currently
shipped. If a required CLI cannot satisfy the documented contract, stop at that
step: changing `unqualified` to `qualified` cannot fix incompatibility. This guide
distinguishes commands you can run now from measurements still required before
an unattended deployment can honestly be called complete.

## Contents

1. [Understand the machines and commands](#1-understand-the-machines-and-commands)
2. [Collect the information you need](#2-collect-the-information-you-need)
3. [Prepare both servers and the source release](#3-prepare-both-servers-and-the-source-release)
4. [Connect the private network](#4-connect-the-private-network)
5. [Prepare the Python dependencies](#5-prepare-the-python-dependencies)
6. [Choose the scripted or manual installation path](#6-choose-the-scripted-or-manual-installation-path)
7. [Prepare accounts and persistent storage](#7-prepare-accounts-and-persistent-storage)
8. [Prepare the execution image and native logins](#8-prepare-the-execution-image-and-native-logins)
9. [Measure capabilities and pin the role release](#9-measure-capabilities-and-pin-the-role-release)
10. [Create private configuration and secrets](#10-create-private-configuration-and-secrets)
11. [Install using the setup scripts](#11-install-using-the-setup-scripts)
12. [Install manually](#12-install-manually)
13. [Start private HTTPS and check the whole system](#13-start-private-https-and-check-the-whole-system)
14. [Submit and follow your first task](#14-submit-and-follow-your-first-task)
15. [Operate, upgrade, roll back and recover](#15-operate-upgrade-roll-back-and-recover)
16. [Troubleshooting](#16-troubleshooting)
17. [Developer checks and project references](#17-developer-checks-and-project-references)

## 1. Understand the machines and commands

| Name in this guide | What it is | What runs there |
| --- | --- | --- |
| **A**, worker, VPS-A | Ubuntu 26.04, 6 virtual CPU cores, 12 GB RAM | One `cursus-runner` Linux account, rootless Podman 5.x, agent/verifier containers, Git workspaces and publication |
| **B**, controller, VPS-B | Ubuntu 26.04, 4 virtual CPU cores, 8 GB RAM | PostgreSQL 16+, `cursus-control`, website, artifact storage, Tailscale Serve |
| **PC** | Your normal computer with a browser and SSH client | Administration and private website access |

No GPU or local model server is required. Agents use remote providers through
native `pi`, `claude`, `codex` and `agy` CLIs **inside the image on A**. B alone
connects to the coordination database. The runner pulls jobs from B over private
HTTPS; B does not SSH into A. Chromebook enrollment is deferred.

A **terminal** is the window where you type commands. Open separate SSH terminals
for A and B and keep their titles distinct. A **service account** is a Linux user
reserved for a program. **Rootless** means containers run under that ordinary
account rather than host root. A **wheel** is a built Python package; a
**wheelhouse** is a directory containing its dependency packages. A **commit** is
an exact Git revision. A **digest** is a checksum identifying exact file bytes.
A **tailnet** is your private Tailscale network.

Commands in `bash` blocks are for Bash on the named server, from the checkout
unless another directory is stated. Do not type the opening/closing backticks.
Run blocks in order, one command at a time; stop on an error. `sudo` uses your
server administrator password, not a provider password. Text such as
`YOUR_REPOSITORY_URL` is a value to replace, not a command to run literally.
JSON uses `true`/`false`; TOML numeric settings use unquoted numbers.

For file edits, `nano /path/to/file` opens an editor: Ctrl+O then Enter saves;
Ctrl+X exits. Use `sudo nano` for root-owned files. Never paste secret files,
full environments or raw login output into issues or chats.

**Finished means:** both services run under their intended accounts, the private
website accepts only your configured Tailscale identity, the runner reconciles,
a bounded authorized task produces real verification evidence and one reviewed
PR, and recovery/credential/isolation checks pass. A green systemd status alone
is insufficient.

## 2. Collect the information you need

Create a private deployment notebook on your PC, outside this repository. Record
non-secret values and results; keep actual credentials in the relevant native
login or password manager. You need:

| Item | How to obtain it / where it goes |
| --- | --- |
| Administrator SSH access to A and B | Server provider's console; test `ssh ADMIN@SERVER` from your PC before changing services |
| Approved source URL and full release commit | Your Cursus checkout/review; use `git rev-parse HEAD` after selecting the reviewed release |
| A/B architecture | `uname -m`; image and wheels must match A/B respectively |
| Tailscale account and exact operator login | Tailscale admin console; copy the login identity, not your display name |
| B's full Tailscale DNS name | Tailscale Machines page after enrollment; for example `controller.example-tailnet.ts.net` |
| One runner UUID | Generate once with `python3 -c 'import uuid; print(uuid.uuid4())'`; put the same value on A and B |
| GitHub owner, repository, target branch | Start with a repository you own and authorize Cursus to change through PRs |
| Repository check command | A real test/build command that works inside the execution image without downloads |
| Provider accounts and selected CLI builds | All four providers; verify plan access and supported unattended login first |
| Capacity, resource and disk policy | Choose the explicit ceilings and budgets in §10; they are not inferred from advertised RAM |
| Provider test budget | Decide maximum invocations, elapsed time, concurrency and money before any live prompt |
| Backup destination and retention | A private location independent of B; backup scheduling/restore automation is not supplied yet |

You will need free storage for PostgreSQL, immutable artifacts, container images,
Git caches and workspaces. Run `df -h / /var /opt` on both servers. There is no
validated fixed disk-size recommendation; choose a reserve and monitor actual
use. Keep administrative recovery access through your provider while changing
network settings. Do not replace an existing firewall policy blindly.

## 3. Prepare both servers and the source release

**On A and B**, check the operating system and hardware:

```bash
cat /etc/os-release
uname -m
python3 --version
nproc
free -m
df -h / /var /opt
```

The installer explicitly requires Ubuntu `VERSION_ID="26.04"`; the Python
package requires CPython 3.12+. A requires cgroup v2:

```bash
test -f /sys/fs/cgroup/cgroup.controllers && cat /sys/fs/cgroup/cgroup.controllers
```

Expected: a list including `cpu`, `memory` and `pids`. If absent, use a server
with supported cgroup delegation; do not remove containment checks to proceed.

Install basic preparation tools on both servers:

```bash
sudo apt-get update
sudo apt-get install --yes git python3-venv ca-certificates curl nano
mkdir -p "$HOME/cursus-deployment"
chmod 700 "$HOME/cursus-deployment"
```

Clone the approved repository into your administrator's home:

```bash
read -r -p 'Cursus Git URL: ' CURSUS_SOURCE_URL
git clone -- "$CURSUS_SOURCE_URL" "$HOME/cursus-source"
cd "$HOME/cursus-source"
read -r -p 'Full reviewed commit (40 lowercase hex characters): ' CURSUS_RELEASE
git checkout --detach "$CURSUS_RELEASE"
git rev-parse HEAD
git status --short
```

Expected: the requested commit and no status output. Use a private operator
checkout for the role customization in §9. Do not commit secrets or machine
inventory. Re-run `git rev-parse HEAD` after that customization: the **final**
commit, not the original public commit, becomes `CURSUS_RELEASE` for installation.
Use that same final commit on both hosts.

If you reconnect later, variables from the old terminal are gone. Return with
`cd "$HOME/cursus-source"`, then set `CURSUS_RELEASE=$(git rev-parse HEAD)`.
Never set it before checking that you are in the intended repository.

## 4. Connect the private network

**On your PC:** install the Tailscale client from the vendor, sign in to the
intended tailnet, and verify the device appears in its Machines page.

**On A and B:** use the Ubuntu instructions on
[Tailscale's Linux installation page](https://tailscale.com/docs/install/linux).
For an inspectable installer workflow:

```bash
curl --fail --show-error --location https://tailscale.com/install.sh --output /tmp/cursus-tailscale-install.sh
less /tmp/cursus-tailscale-install.sh
sudo sh /tmp/cursus-tailscale-install.sh
sudo tailscale up
tailscale status
```

`less` exits with `q`. Review the downloaded installer before executing it.
`tailscale up` gives you an enrollment URL if login is needed: open it on your
PC, sign in, and approve the correct machine. Do not paste enrollment URLs into
public records. Record the installed version with `tailscale version`.

In the admin console, enable MagicDNS and HTTPS certificates for Serve if
prompted. Record B's complete DNS name. Your exact origin will be
`https://B_FULL_TAILSCALE_DNS_NAME`, with **no trailing slash**.

Check private reachability from A and PC using `tailscale ping B_FULL_TAILSCALE_DNS_NAME`.
Expected: a successful peer response. Establish tailnet access rules allowing
only A and intended operator devices to reach B's Serve HTTPS port (443), plus
your separately approved administration access. Check the effective policy with
the Tailscale console's policy tests; enrollment alone does not restrict peers.

Do not open public ports 8787 or 5432. Keep B's application on `127.0.0.1` and
PostgreSQL local. **Do not enable Tailscale Funnel**: Serve is private to the
tailnet, Funnel is public. Serve is started only after B's backend works in §13.
See [the Serve documentation](https://tailscale.com/docs/features/tailscale-serve)
for its enrollment and private HTTPS behavior.

## 5. Prepare the Python dependencies

Do this on **each target host**, or on a matching OS/architecture/Python machine
and transfer its wheelhouse to that host. A wheelhouse prepared for a different
Python or CPU architecture may not work.

From `~/cursus-source`:

```bash
python3 -m venv "$HOME/cursus-build-env"
"$HOME/cursus-build-env/bin/python" -m pip download --require-hashes --only-binary=:all: --dest "$HOME/cursus-deployment/wheels" -r requirements.lock
"$HOME/cursus-build-env/bin/python" -m pip install --no-index --find-links "$HOME/cursus-deployment/wheels" --require-hashes -r requirements.lock
PIP_NO_INDEX=1 "$HOME/cursus-build-env/bin/python" -m build --wheel --no-isolation
"$HOME/cursus-build-env/bin/python" -m pip install --no-index --no-deps dist/cursus-0.5.0-py3-none-any.whl
"$HOME/cursus-build-env/bin/python" -m pip check
"$HOME/cursus-build-env/bin/cursus" --version
```

Expected: dependency download/install succeeds, `pip check` reports no broken
requirements and the version is `cursus 0.5.0`. The lock includes the build tools;
no global pip install is needed. If a compatible wheel is missing, stop and
prepare a reviewed wheelhouse for the target; do not remove hash checking.

This does not log in to any model provider or start Cursus. Python dependency
installation and native agent installation are separate tasks.

## 6. Choose the scripted or manual installation path

Both paths use the same config, image, profiles, accounts and immutable release
layout. Both need §§7–10 first; neither can invent provider capability evidence.

| Path | Use it when | What you do after preparation |
| --- | --- | --- |
| Setup scripts | The hosts are Ubuntu 26.04 and you want repeatable staging/activation | §11, then §13 onward; skip §12 |
| Manual | You need to see/control every install step | §12, then §13 onward; skip §11 |

The scripts install host packages/accounts and build a private-configured release.
They do **not** enroll Tailscale, set access policies, build the agent image,
perform provider login, provision publisher credentials, prepare your artifact
root, finish role profiles or set up backups. Running a dry-run is useful but is
not proof of a working installation.

## 7. Prepare accounts and persistent storage

These commands assume **new dedicated hosts**, with no existing Cursus accounts.
If `getent passwd cursus-runner` on A or `getent passwd cursus-control` on B
already returns an account, inspect its home/shell and existing deployment first;
do not recreate it, change its UID or recursively change ownership. The scripts
require the stable homes below and `/usr/sbin/nologin` shells.

**A:**

```bash
sudo apt-get install --yes --no-install-recommends podman uidmap passt
sudo useradd --user-group --create-home --home-dir /var/lib/cursus-runner --shell /usr/sbin/nologin cursus-runner
sudo chmod 700 /var/lib/cursus-runner
sudo loginctl enable-linger cursus-runner
sudo install -d -m 700 -o cursus-runner -g cursus-runner /etc/cursus/runner
sudo install -d -m 700 -o cursus-runner -g cursus-runner /var/lib/cursus-runner/state /var/lib/cursus-runner/spool /var/lib/cursus-runner/repositories /var/lib/cursus-runner/worktrees /var/lib/cursus-runner/reviews /var/lib/cursus-runner/auth
```

Define a convenience function in A's administrator terminal. All subsequent
`runner ...` commands in this README refer to this function:

```bash
CURSUS_RUNNER_UID=$(id -u cursus-runner)
runner() {
  sudo runuser -u cursus-runner -- env -i \
    HOME=/var/lib/cursus-runner PATH=/usr/bin:/bin LANG=C.UTF-8 \
    XDG_RUNTIME_DIR="/run/user/$CURSUS_RUNNER_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$CURSUS_RUNNER_UID/bus" "$@"
}
sudo systemctl start "user@$CURSUS_RUNNER_UID.service"
runner systemctl --user is-system-running
runner podman --version
runner podman info --format '{{.Host.CgroupVersion}} {{.Host.CgroupManager}} {{.Host.Security.Rootless}}'
sudo awk -F: '$1 == "cursus-runner" {print $1, $2, $3}' /etc/subuid /etc/subgid
```

Expected: Podman `5.x`, info `v2 systemd true`, and one subordinate range of at
least 65536 IDs in **each** file. A user manager may report `degraded`; inspect
`runner systemctl --user --failed` rather than assuming it is healthy. If ranges
are missing, allocate unused, non-overlapping UID/GID ranges using your host's
allocation policy before using Podman. Never copy another user's ranges or use
an arbitrary number that could overlap them.

**B:**

```bash
sudo apt-get install --yes --no-install-recommends postgresql
sudo useradd --user-group --create-home --home-dir /var/lib/cursus-control --shell /usr/sbin/nologin cursus-control
sudo groupadd --force cursus-operators
sudo usermod --append --groups cursus-operators cursus-control
sudo usermod --append --groups cursus-operators "$(id -un)"
sudo chmod 700 /var/lib/cursus-control
sudo install -d -m 700 -o cursus-control -g cursus-control /etc/cursus/control /var/lib/cursus-control/artifacts /var/backups/cursus
sudo systemctl enable --now postgresql
psql --version
pg_isready
```

Expected PostgreSQL 16+ and accepting local connections. Log out of SSH and back
in so your new operator-group membership takes effect. Verify `id -nG` includes
`cursus-operators`. Re-enter the checkout and reset your shell variables.

For the **manual path only**, create B's local database role and database now:

```bash
sudo -u postgres createuser --no-superuser --no-createdb --no-createrole cursus-control
sudo -u postgres createdb --owner=cursus-control cursus
```

The scripted path creates them during staging. If either already exists, inspect
its ownership and privileges with your database administrator; do not drop it or
continue against an unrelated database. Use local peer authentication: Linux
`cursus-control` connects as database `cursus-control` with no password argument.

## 8. Prepare the execution image and native logins

**On A.** Podman stores images separately for each Linux user. An image loaded as
root is not automatically visible to `cursus-runner`; use `runner podman ...`.

### 8.1 Image contents

Build a reviewed Linux image matching A's architecture containing:

- `/usr/bin/sleep` (Cursus replaces the entrypoint with `sleep infinity`).
- Direct native executables named `pi`, `claude`, `codex`, `agy`, at the absolute
  paths recorded in your capability file (the worksheet uses `/usr/local/bin`).
- Their runtime dependencies, such as Node where the selected distribution needs
  it. Do not assume a host runtime is visible inside the image.
- Git and your enrolled repository's build/test tools and dependencies. Verifiers
  have **no network**, so checks must not download packages at runtime.
- A writable-workspace-compatible toolchain running as UID/GID `1000:1000` with
  `HOME=/home/session`, read-only image root and disposable `/tmp`/HOME.

The image must contain **no credentials**, login tokens, copied personal home,
automatically loaded executable extensions or publisher credentials. Pin vendor
versions and base image digests. Retain its Containerfile, artifact checksums and
build log privately so you can rebuild and requalify it.

Use the official distribution instructions for the selected builds:
[pi](https://upd.dev/badlogic/pi-mono/src/branch/main/packages/coding-agent/README.md),
[Claude Code](https://code.claude.com/docs/en/setup),
[Codex CLI](https://developers.openai.com/codex/cli), and
[Antigravity CLI](https://antigravity.google/docs/cli-getting-started).
Download and review installation artifacts before running them, select exact
versions, and install **during image build**, not in running Cursus sessions.
These links explain vendor distribution, not evidence that those builds satisfy
Cursus's contract. The repository currently ships no qualified Containerfile or
pinned four-vendor bundle; this remains a deployment prerequisite, not a step
the setup scripts secretly perform.

If you receive an approved image archive from your release process:

```bash
read -r -p 'Absolute path to approved image archive: ' CURSUS_IMAGE_ARCHIVE
runner podman load --input "$CURSUS_IMAGE_ARCHIVE"
runner podman images --no-trunc
```

Or, once you have a reviewed build directory with a `Containerfile`:

```bash
read -r -p 'Absolute path to reviewed image build directory: ' CURSUS_IMAGE_BUILD
runner podman build --pull=never --tag localhost/cursus-execution:qualified "$CURSUS_IMAGE_BUILD"
```

`--pull=never` requires its reviewed base image already loaded for this account.
The build directory must be readable/traversable by the runner; do not loosen
permissions on your whole home to achieve that. Record the resulting image:

```bash
runner podman image inspect localhost/cursus-execution:qualified --format '{{.Id}}'
```

For a differently tagged imported image, substitute its tag. Save the full
`sha256:` plus 64 hex digits as `containers.image` and the capability `image`.
A tag is insufficient because tags can move. Runtime never pulls automatically.

### 8.2 Authentication directories

Each simultaneous provider invocation needs its own disjoint **native auth-only
directory**. For example, a pi ceiling of two needs `pi-1` and `pi-2`, even if all
sessions use the same provider account. Separate directories do not prove the
provider supports simultaneous refresh; that must be measured.

Create the exact domain directories you chose, for example:

```bash
sudo install -d -m 700 -o cursus-runner -g cursus-runner /var/lib/cursus-runner/auth/pi-1 /var/lib/cursus-runner/auth/claude-1 /var/lib/cursus-runner/auth/codex-1 /var/lib/cursus-runner/auth/agy-1
```

Repeat for additional chosen domains. For each vendor, determine its supported
native auth directory from that **installed version**, enroll through its native
interactive login in an isolated provisioning container, and persist only that
directory as the configured bind mount. Mount targets must be subdirectories
of `/home/session`, never all of HOME. Never seed them by copying your PC's,
another user's or the developer agent's credential store.

Important compatibility check: Antigravity documents native keyring use and
headless alternatives on its [authentication page](https://antigravity.google/docs/install).
This backend does not mount a host keyring, D-Bus socket or arbitrary API-key
environment. If your chosen native auth needs those, it does not yet fit the
backend. Establish a supported directory-only native flow or record a required
implementation change; do not expose the host session bus as a workaround.

For each chosen version/domain, record the exact login command, mounted native
subdirectory, renewal command, expiry behavior and recovery steps privately.
There is currently no verified cross-vendor login command sequence in this
repository. Do not proceed to activation until these records and working logins
exist. Login may require opening a vendor URL on PC; the runtime must later work
without a browser, approval prompt, copied credentials or interactive input.

## 9. Measure capabilities and pin the role release

A capability profile records **observed behavior**, not desired behavior. Use
`deploy/capabilities.example.toml` as a worksheet. Preserve measurements outside
the public repository. Complete one base profile per CLI and overrides where a
role needs different tools or transport.

Before live tests, write down a finite budget: maximum process invocations,
one in-flight invocation per provider initially, at least one second between
same-provider starts unless vendor limits require longer, maximum wall time,
authorized monetary ceiling and a working process/container stop procedure.
A useful first auth batch is one invocation per CLI, each at most 120 seconds
plus a 10-second termination grace, no harness retries. This bounds processes,
not hidden provider requests or billable spend. Obtain your own budget approval
before running it; this README authorizes no provider spending.

Test in disposable workspaces using only your separately provisioned native
logins. Never inherit the developer-agent environment or keys. Start with
`Reply with exactly CURSUS_M0_OK. Do not use tools.` Stop on auth denial,
throttling, unexpected approval prompts or unknown termination; honor vendor
cooldowns. Independent providers need not wait for another provider's cooldown.

Then establish these exact contracts in the pinned image and sandbox:

| CLI / role | Invocation and observations required |
| --- | --- |
| pi worker/debug | Direct `pi --mode rpc` family; correlated `response`, assistant `message_end`, `agent_end`; prompt/steer/abort; same RPC process across debug turns |
| pi scout | Read-only `pi --mode json` family with explicit tool restriction; normally needs `[pi.role_profiles.scout]` overriding RPC worker settings |
| Claude organization roles | `claude -p --output-format stream-json` family; supported read-only tools; terminal `result` with subtype `success` |
| Codex reviewer/organization roles | `codex exec --json` family; read-only tools; `item.completed` agent message and `turn.completed` |
| Antigravity organization roles | `agy -p --output-format stream-json` family; read-only tools; terminal `result` with subtype `success` |

The family prefixes above are **not complete runnable commands**. Append the
installed-version model/provider/reasoning/config-isolation flags and establish
prompt transport from its help and bounded probes. Record literal argument
arrays; do not embed shell commands, pipes or shell expansion in TOML argv.

For every profile fill `binary`, `version`, `binary_digest`, `model`, `reasoning`,
`qualified_roles`, `fixed_argv`, `prompt_transport`, `tool_allowlist`,
`clean_config_argv`, `probe_evidence`, and `credential_concurrency`; pi also needs
the actual OpenCode Go provider identifier. OpenRouter is prohibited. Record
success/failure/turn signatures, renewal procedures and correlation evidence.
`fixed_argv` excludes the executable itself. The launcher appends
`read_only_argv` for organizational/scout roles, then `clean_config_argv`.

Match each role in `roles.toml` exactly: model, reasoning, optional provider and
**the entire tool set** must equal its effective profile. Worker/debug use
`read,list,search,write,edit,bash`; scout/organization use `read,list,search`.
An override merges over its base profile, so explicitly replace inherited tool
and transport settings. `credential_concurrency` must cover the configured
ceiling for that provider, supported by concurrent renewal/expiry/recovery
measurements using disjoint domains. Only after successful evidence set the
worksheet's top-level `qualification = "qualified"` and schema version 2.

Hash the finalized capability file on A (this is not a secret):

```bash
sha256sum "$HOME/cursus-deployment/capabilities.toml"
```

Put its 64-character digest in `roles.toml`'s `profile_digest` and runner config's
`service.capabilities_digest`. Put the same image ID in profile and runner config.

**Resolve the release ordering before installing:** control rejects dirty or
uncommitted role/prompt bytes. In a private operator Git checkout, fill the
non-secret model/reasoning/provider tuples and profile digest in `roles.toml`,
review the diff, and commit those role changes through your release workflow.
Do not commit host configs, auth directories or private evidence. This creates a
new deployment commit. Set `CURSUS_RELEASE` to its full commit ID and set
`control.toml`'s `role_release_commit` to it. Transfer that exact committed source
to both hosts through your approved private release transport. Do not merely
edit `/opt/cursus/current/source/roles.toml` after installation.

Changing the image, executable, flags, model, permissions, profile bytes or
credential concurrency invalidates affected measurements and may need a new
committed role release. There is no automatic compatibility discovery.

## 10. Create private configuration and secrets

### 10.1 Copy and edit configuration

**B:**

```bash
cp deploy/control.example.toml "$HOME/cursus-deployment/control.toml"
chmod 600 "$HOME/cursus-deployment/control.toml"
nano "$HOME/cursus-deployment/control.toml"
```

**A:**

```bash
cp deploy/runner.example.toml "$HOME/cursus-deployment/runner.toml"
chmod 600 "$HOME/cursus-deployment/runner.toml"
nano "$HOME/cursus-deployment/runner.toml"
```

Set all of the following; do not leave any `REPLACE_*` text:

| Location | Setting | Value |
| --- | --- | --- |
| B service | `external_origin` | Exact `https://` B tailnet DNS origin, no path/trailing slash |
| B service | `operator_login` | Exact Tailscale login of the one authorized operator |
| B service | `role_release_commit` | Final committed qualified role release from §9 |
| B runner | `id`, `tailnet_node` | Shared runner UUID and actual A tailnet node |
| B backup | `off_host_destination` | Your private backup destination; this field does not schedule backups |
| A service | `origin`, `runner_id` | Same B HTTPS origin and runner UUID |
| A service | `capabilities_digest` | SHA-256 of the finalized capability file |
| A containers | `version`, `image` | Exact installed Podman `5.x.y` and full qualified image ID |
| Both | `capacity` | Identical integer ceilings, as below |
| Both | `repositories` | Identical owner/name/object format, full allowed target refs and checks |
| A containers | `credentials` | Exactly one qualified domain per configured simultaneous provider invocation |

Leave `listen_host = "127.0.0.1"`, port 8787, socket and service user paths as
shown unless you also deliberately adapt the service units and all references.
Schema 2 is required. Keep the template's other limits initially; they bound
requests, retries and artifacts rather than authorizing spending.

### 10.2 Choose capacity and resources explicitly

`worker` means all simultaneous pi invocations, including scout/debug. It must
be 1–4. Each of `claude`, `codex`, `agy` must independently be 1–2.
`verifier = 1` and `repository = 1` remain separate lanes. These are ceilings,
not a promise that all can run simultaneously. Do not put quoted strings in
numeric fields. A domain count must equal its corresponding ceiling.

Resource units: `memory_mb`, `tmp_mb`, `home_mb`, `disk_reserve_mb` are MiB-sized
limits in this implementation; `cpu_millis = 1000` means one CPU core;
`pids` includes process/thread tasks. Set:

- `containers.budget`: total execution memory/CPU/PID allowance and host
  memory/CPU reserves. Execution memory + host reserve must fit both 12288 MiB
  and observed host memory; CPU + reserve must fit both 6000 and observed CPUs.
- `containers.resources.agent`: per-agent memory, CPU, PID, temporary-directory
  and disposable-HOME limits.
- `containers.resources.verifier`: the independent per-verifier limits.
- `containers.disk_reserve_mb`: free-space floor below which admission stops.

For memory/CPU/PIDs, total budget must admit **one agent plus one verifier**.
For each class, `tmp_mb + home_mb < memory_mb`. Agents share a slice capped at
budget minus verifier allowance. More sessions wait when resources do not fit;
waiting/unknown containers continue to consume reservations. Increasing a ceiling
does not increase the hardware budget. Choose policy values, then measure
workloads; this repository does not establish safe universal numeric defaults.

### 10.3 Enroll a repository and its checks

On **both** configs, replace the entire example enrollment with the same trusted
GitHub repository and target, for example `refs/heads/main`. A check's `argv[0]`
is an absolute executable path **inside the container image**. Do not copy the
controller template's `/opt/cursus/venv/bin/python` unless your image actually
contains it. For a Python unittest repository the runner template's
`["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests/unit"]` is suitable
only when those tests and dependencies really exist. Set `cwd` to `.` or a
repository-relative directory, a positive timeout, and `phase_check_ids` to
existing check IDs. Checks run without network or publisher credentials.

Ensure GitHub branch/ruleset and automation policy prevents this publisher from
merging or directly updating the enrolled target. Cursus only publishes its own
work/integration refs and creates PRs. Token permissions alone usually do not
express that complete branch restriction; test the effective repository rules.

### 10.4 Create the runner bearer without displaying it

**A:** generate the secret file under the stable runner account:

```bash
runner /usr/bin/python3 - <<'PY'
import hashlib, os, secrets
from pathlib import Path
path = Path('/etc/cursus/runner/bearer')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
token = secrets.token_urlsafe(48)
with os.fdopen(fd, 'w') as stream:
    stream.write(token + '\n')
print('Runner bearer created. SHA-256 for B:', hashlib.sha256(token.encode()).hexdigest())
PY
```

Copy **only the printed digest**, not the token, into B's digest file:

```bash
sudo -u cursus-control nano /etc/cursus/control/runner-bearer.sha256
sudo chmod 600 /etc/cursus/control/runner-bearer.sha256
```

Enter the 64 hex characters on one line, save and exit. If the A file already
exists, the command refuses to overwrite it. On an existing deployment preserve
the established pairing or plan an explicit rotation; do not generate one per
restart.

**B:** create the local DSN (a database connection address) without a password:

```bash
sudo -u cursus-control sh -c 'umask 077; printf "%s\n" "postgresql:///cursus?host=/var/run/postgresql" > /etc/cursus/control/database-dsn'
```

For the manual path, verify now; for the scripts path, verify after staging:

```bash
sudo -u cursus-control psql --no-psqlrc --dbname='postgresql:///cursus?host=/var/run/postgresql' --command='SELECT current_user, current_database();'
```

Expected: `cursus-control` and `cursus`. Do not weaken PostgreSQL authentication
or put the DSN on A if this fails.

### 10.5 Provision publication credentials and capability file

**A:** provision a dedicated GitHub publisher credential through your approved
secret-management/native enrollment flow. It needs repository access for Cursus
refs and PR creation, subject to the target protections above. The two paths
have **different formats**:

| File | Contents consumed by code |
| --- | --- |
| `/etc/cursus/runner/publisher-git-credential` | Git `credential-store` format: HTTPS credential entry for github.com, not a bare token |
| `/etc/cursus/runner/publisher-github-credential` | Bare GitHub bearer token text for the REST API, not a credential-store URL |

Have the secret manager write these as regular `0600` files owned by
`cursus-runner`. Do not put token text in shell command arguments, source,
terminal logs or the image. If entering them manually, use a private interactive
editor under `sudo -u cursus-runner` for those exact files and verify ownership
and modes without printing contents:

```bash
sudo stat -c '%U %G %a %n' /etc/cursus/runner/publisher-git-credential /etc/cursus/runner/publisher-github-credential
sudo install -m 600 -o cursus-runner -g cursus-runner "$HOME/cursus-deployment/capabilities.toml" /etc/cursus/runner/capabilities.toml
```

Keep credential management and replacement separate from Cursus workspaces.
The stable runner consumes them; session containers must never receive them.

## 11. Install using the setup scripts

Skip §12 after this section. On **each host**, return to the final clean source
checkout and define:

```bash
cd "$HOME/cursus-source"
CURSUS_RELEASE=$(git rev-parse HEAD)
git status --short
```

Expected: no changes. The configuration, wheelhouse and private evidence must
remain outside this checkout. Do not put them there to make relative paths easier.

### 11.1 Preview, then stage

**B:**

```bash
sh deploy/setup-controller.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/control.toml" --wheelhouse "$HOME/cursus-deployment/wheels" --dry-run
sudo sh deploy/setup-controller.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/control.toml" --wheelhouse "$HOME/cursus-deployment/wheels" --apply
```

**A:**

```bash
sh deploy/setup-worker.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/runner.toml" --wheelhouse "$HOME/cursus-deployment/wheels" --dry-run
sudo sh deploy/setup-worker.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/runner.toml" --wheelhouse "$HOME/cursus-deployment/wheels" --apply
```

Without `--apply`, scripts only print a plan; `--dry-run` makes that explicit.
Do not combine both flags. Staging installs required packages, checks/creates
stable accounts, builds the wheel/venv offline and stores the exact config under:

```text
/opt/cursus/releases/FULL_COMMIT-FIRST_16_HEX_OF_CONFIG_SHA256/
  source/          committed source, roles and prompts
  venv/            isolated installed Python package
  wheels/          built Cursus wheel
  config.toml      private host-specific config
  complete.json    completed-stage marker
```

Each host has its own `/opt/cursus/current` symlink, which is not switched during
staging. A completed identical stage is reusable. An incomplete stage is retained
for inspection and blocks blind reuse. Success ends with `Completed installation`.
This means **staged**, not started. Check B's authenticated database connection
using §10.4 now.

### 11.2 Activate B, then A

**B:**

```bash
sudo sh deploy/setup-controller.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/control.toml" --activate-existing --apply
sudo systemctl status cursus-control --no-pager
```

Activation validates pinned roles/config/secrets, switches `current`, installs
the system service and starts it. B applies database migrations before listening.
Complete §13's Serve setup on B before starting A so A can reach its HTTPS origin.

**A:**

```bash
sudo sh deploy/setup-worker.sh --release "$CURSUS_RELEASE" --config "$HOME/cursus-deployment/runner.toml" --activate-existing --apply
runner systemctl --user status cursus-runner --no-pager
```

Worker activation checks exact Podman version, rootless cgroup support, local
image and native concurrency profile. It generates aggregate/agent/verifier
execution slices from the configured budgets and enables the user service.
It does not run paid provider qualification for you. Proceed to §13 checks.

For upgrades, activation requires drain and no unresolved attempts/queued jobs;
see §15 before using these commands on an active installation. Never run a legacy
root/system runner alongside the new user service.

## 12. Install manually

This is the alternative to §11. It preserves the same release layout, private
config and systemd boundaries. Complete §§7–10 first, including the manual DB
creation. Run on **both** hosts unless a step says otherwise.

### 12.1 Build the immutable release

From the final clean source checkout, set the host-specific values:

```bash
cd "$HOME/cursus-source"
CURSUS_RELEASE=$(git rev-parse HEAD)
git status --short
```

**A:**

```bash
CURSUS_SERVICE_USER=cursus-runner
CURSUS_CONFIG="$HOME/cursus-deployment/runner.toml"
```

**B:**

```bash
CURSUS_SERVICE_USER=cursus-control
CURSUS_CONFIG="$HOME/cursus-deployment/control.toml"
```

**Both:**

```bash
CURSUS_CONFIG_ID=$(sha256sum "$CURSUS_CONFIG" | cut -c1-16)
CURSUS_STAGE="/opt/cursus/releases/$CURSUS_RELEASE-$CURSUS_CONFIG_ID"
sudo test ! -e "$CURSUS_STAGE"
```

Continue only if the last command succeeds. If the stage exists, inspect it;
do not overwrite immutable files or delete an unknown stage. Also verify
`git status --short` was empty and HEAD is the reviewed qualified release.

```bash
sudo install -d -m 755 "$CURSUS_STAGE"
sudo git clone --local --no-hardlinks --no-checkout "$PWD" "$CURSUS_STAGE/source"
sudo git -C "$CURSUS_STAGE/source" -c core.hooksPath=/dev/null checkout --detach "$CURSUS_RELEASE"
sudo git -C "$CURSUS_STAGE/source" remote remove origin
sudo python3 -m venv "$CURSUS_STAGE/venv"
sudo "$CURSUS_STAGE/venv/bin/python" -m pip install --no-index --find-links "$HOME/cursus-deployment/wheels" --require-hashes -r "$CURSUS_STAGE/source/requirements.lock"
sudo env PIP_NO_INDEX=1 "$CURSUS_STAGE/venv/bin/python" -m build --wheel --no-isolation --outdir "$CURSUS_STAGE/wheels" "$CURSUS_STAGE/source"
sudo "$CURSUS_STAGE/venv/bin/python" -m pip install --no-index --no-deps "$CURSUS_STAGE/wheels/cursus-0.5.0-py3-none-any.whl"
sudo "$CURSUS_STAGE/venv/bin/python" -m pip check
sudo install -m 600 -o "$CURSUS_SERVICE_USER" -g "$CURSUS_SERVICE_USER" "$CURSUS_CONFIG" "$CURSUS_STAGE/config.toml"
sudo "$CURSUS_STAGE/venv/bin/cursus" --version
```

Expected: version 0.5.0, no missing requirements. Root owns source/venv; the
service user may read them but must not edit installed code.

### 12.2 Validate before switching

**Both**, validate as the actual service user; this consumes secret files
opaquely and prints no settings:

```bash
CURSUS_KIND=control
```

On **A**, override that value with `CURSUS_KIND=runner`. Then on both:

```bash
sudo runuser -u "$CURSUS_SERVICE_USER" -- "$CURSUS_STAGE/venv/bin/python" -c 'from cursus.config import load; import sys; load(sys.argv[1], sys.argv[2], release_root=sys.argv[3]); print("Configuration loaded")' "$CURSUS_KIND" "$CURSUS_STAGE/config.toml" "$CURSUS_STAGE"
```

Expected: `Configuration loaded`. Missing secrets, digest mismatches, unfinished
roles and native-concurrency shortfalls must be corrected before activation.
On **A** also run:

```bash
runner "$CURSUS_STAGE/venv/bin/python" -c 'import asyncio,sys; from cursus.config import load; from cursus.containers import Containers; s=load("runner",sys.argv[1]); asyncio.run(Containers(s["containers"],s["service"]["state_root"]+"/execution",s["capacity"]).preflight()); print("Runtime preflight passed")' "$CURSUS_STAGE/config.toml"
```

This validates runtime inventory, not actual provider login or namespace/resource
qualification. Do not mark live acceptance passed from this output alone.

On **both**, create the completed marker only after these checks succeed:

```bash
sudo "$CURSUS_STAGE/venv/bin/python" -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1])/"complete.json"; f=p.open("x"); json.dump({"commit":sys.argv[2]},f); f.close()' "$CURSUS_STAGE" "$CURSUS_RELEASE"
```

### 12.3 Install B's unit and A's resource slices

**B:**

```bash
sudo install -m 644 "$CURSUS_STAGE/source/deploy/cursus-control.service" /etc/systemd/system/cursus-control.service
```

**A:**

```bash
sudo install -d -m 755 -o cursus-runner -g cursus-runner /var/lib/cursus-runner/.config/systemd/user
sudo install -m 644 "$CURSUS_STAGE/source/deploy/cursus-runner.service" /var/lib/cursus-runner/.config/systemd/user/cursus-runner.service
sudo "$CURSUS_STAGE/venv/bin/python" - "$CURSUS_STAGE/config.toml" <<'PY'
import sys, tomllib
from pathlib import Path
with open(sys.argv[1], 'rb') as source:
    config = tomllib.load(source)
budget = config['containers']['budget']
verifier = config['containers']['resources']['verifier']
root = Path('/var/lib/cursus-runner/.config/systemd/user')
for name, values in (
    ('cursus-execution.slice', budget),
    ('cursus-execution-agents.slice', {k: budget[k]-verifier[k] for k in ('memory_mb','cpu_millis','pids')}),
    ('cursus-execution-verifier.slice', verifier),
):
    text = ('[Unit]\nDescription=Cursus execution budget\n[Slice]\n'
            f'MemoryMax={values["memory_mb"]}M\n'
            f'CPUQuota={values["cpu_millis"]/10}%\nTasksMax={values["pids"]}\n')
    (root / name).write_text(text)
    (root / name).chmod(0o644)
PY
```

These caps match the launcher's admission policy. Do not omit the slices or
collapse the verifier reserve into the agent slice. Podman needs delegated
user namespaces/cgroups: do not add `NoNewPrivileges` or `RestrictNamespaces`
to the runner service to imitate B's stricter controller unit.

### 12.4 Switch and start (new installation)

The following commands are for **first installation only**. On both hosts,
verify `/opt/cursus/current` does not already exist. For an upgrade, use §15's
drain/migration checks and scripted activation of this staged release instead;
manual installation is not permission to bypass those gates.

```bash
sudo test ! -e /opt/cursus/current
sudo test ! -L /opt/cursus/current
sudo test ! -e /opt/cursus/current.next
sudo ln -s "$CURSUS_STAGE" /opt/cursus/current.next
sudo mv -T /opt/cursus/current.next /opt/cursus/current
readlink -f /opt/cursus/current
```

Expected: the exact new stage path. **B first:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cursus-control
sudo systemctl status cursus-control --no-pager
```

Set up Serve in §13 before starting **A**:

```bash
runner systemctl --user daemon-reload
runner systemctl --user start cursus-execution.slice cursus-execution-agents.slice cursus-execution-verifier.slice
runner systemctl --user enable --now cursus-runner
runner systemctl --user status cursus-runner --no-pager
```

## 13. Start private HTTPS and check the whole system

### 13.1 Check B locally, then enable Serve

**B:**

```bash
sudo systemctl is-active cursus-control
sudo journalctl -u cursus-control -n 80 --no-pager
/opt/cursus/current/venv/bin/cursus status --deployment
/opt/cursus/current/venv/bin/cursus status
sudo ss -lntup
```

Expected: active service, usable operator JSON responses, application listener
only on `127.0.0.1:8787`, and no public database listener. If you just joined the
operator group and access is denied, reconnect before changing permissions.

Enable the private reverse proxy on B:

```bash
sudo tailscale serve --bg http://127.0.0.1:8787
tailscale serve status
```

If Serve presents a feature-enablement URL, open it on PC, enable private HTTPS
for the intended tailnet, then repeat once. Verify the displayed HTTPS origin
matches both TOMLs exactly. This command is for a dedicated node with no existing
Serve routing; inspect existing routes first on a reused machine.

Open that HTTPS URL on **PC while connected to Tailscale**. Expected: Cursus's
real overview. No second Cursus password is required: the exact Serve-provided
Tailscale login is the browser identity. A bearer token is for the runner, not
browser login. Direct browser access to `http://B:8787` is neither required nor
supported. Session tokens are invalidated by a controller restart; reload then.

### 13.2 Confirm A's authenticated contact

**A**, after activation:

```bash
runner systemctl --user is-active cursus-runner
runner journalctl --user -u cursus-runner -n 80 --no-pager
runner podman ps --all
```

On **B**, refresh Cursus and run `cursus status` using the full path above.
Wait for fresh reconciled runner contact and the intended independent capacity
ceilings. An empty Podman list while idle is normal. Unknown/cleanup-pending
executions, old heartbeats or unexpected waiting reasons must be resolved before
submitting real work. Do not print raw credential-bearing diagnostics publicly.

### 13.3 Acceptance checklist

Record results privately at the exact release commit/image/profile digests:

- B authenticated database connection and migrations succeed; only B has a DSN.
- B's operator socket is `0660` for the authorized group; application stays local.
- Authorized PC can use Serve; another unauthorized tailnet identity is denied.
  No public Cursus/DB route or Funnel is enabled. Check effective provider firewall
  and tailnet policy as well as local listeners.
- A runs as the stable non-root account, through its user manager and Podman 5.x;
  exact image/profile and provider ceilings match both configs.
- Actual containers enforce non-root IDs, read-only root, private namespaces,
  mount allowlists, resource limits and descendant stop/removal. Fixture tests
  are not substitutes for those intended-host observations.
- Native logins work unattended; directory-only renewal and requested concurrent
  domains have measured support. No host management socket/publisher secret is
  exposed to sessions.
- The authorized end-to-end task in §14 produces independent checks/review and a
  PR at the exact verified head without modifying/merging the target branch.
- A bounded stop/restart/recovery exercise retains unknown ownership until real
  stop/removal is confirmed; no uncertain execution is automatically relaunched.

The detailed [qualification checklist](tests/qualification.md) and
[container finding matrix](docs/acceptance/container-execution.md) define the
remaining M3-end qualification. Keep an item pending when it has not been run.

## 14. Submit and follow your first task

Use an expendable **enrolled GitHub repository** and a small clearly bounded
change. This step invokes paid/subscription providers and writes GitHub refs/PRs;
first establish the call/time/concurrency/cost budget and termination mechanism
from §9. Do not use a production task as an authentication experiment.

**PC browser:** open the private Cursus URL, choose the new-work form, select code
work and the enrolled repository, and provide an inline specification. Initially
leave spec/plan debates off; they add provider calls. State the desired change,
allowed files, acceptance checks and what must remain unchanged.

Or **B terminal**, create `~/cursus-deployment/first-task.json`:

```json
{
  "workflow": "code",
  "form": "one-shot",
  "source": {
    "kind": "inline",
    "text": "In this disposable repository, add a short explanation of the existing test command to README.md. Change no code or dependencies. Acceptance: README describes the actual enrolled test command; existing tests pass."
  },
  "repo": {
    "owner": "YOUR_GITHUB_OWNER",
    "name": "YOUR_ENROLLED_REPOSITORY",
    "target_ref": "refs/heads/main"
  },
  "plan_debate": false,
  "spec_debate": false
}
```

Replace owner/name/target with the exact enrolled values. Generate and keep one
request UUID so a lost response can be retried without submitting duplicate work:

```bash
CURSUS_REQUEST_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
printf '%s\n' "$CURSUS_REQUEST_ID" > "$HOME/cursus-deployment/first-task-request-id"
/opt/cursus/current/venv/bin/cursus submit --input "$HOME/cursus-deployment/first-task.json" --idempotency-key "$CURSUS_REQUEST_ID"
```

Save the returned `entity_id` (phase UUID) and `request_id`. Read status:

```bash
read -r -p 'Phase UUID from submit response: ' CURSUS_PHASE_ID
/opt/cursus/current/venv/bin/cursus status --phase-id "$CURSUS_PHASE_ID"
```

The browser shows phase/attempt progress, checks, findings and evidence. Wait
for a confirmed PR link and download the real check logs. Inspect the PR on
GitHub; confirm only the intended changes and target branch remains unchanged.
**Final merge is your action**, not Cursus's. If interrupted, inspect status and
reconcile; do not submit again under a fresh UUID just because the first response
was lost. The same UUID with different input is rejected as a conflict.

## 15. Operate, upgrade, roll back and recover

### Daily operations

| Task | B | A (with the §7 `runner` function) |
| --- | --- | --- |
| Status | `sudo systemctl status cursus-control` | `runner systemctl --user status cursus-runner` |
| Recent logs | `sudo journalctl -u cursus-control -n 80` | `runner journalctl --user -u cursus-runner -n 80` |
| Stop | `sudo systemctl stop cursus-control` | `runner systemctl --user stop cursus-runner` |
| Start | `sudo systemctl start cursus-control` | `runner systemctl --user start cursus-runner` |
| Active release | `readlink -f /opt/cursus/current` | Same command on A |

Before an operational stop, drain and finish active work if possible. Restarting
the runner cannot reconnect to an old native RPC stdin channel; Cursus reconciles
and stops the positively identified old container, then reports interruption.
Do not use restart as an assumption-free way to continue an active debug session.

### Drain and upgrade

1. Record both current release paths, source commits, config/profile/image
   digests and database migration history. Preserve the exact private configs
   and qualified image; a source tag alone cannot reproduce the deployment.
2. On B, create a non-secret action file:

   ```bash
   printf '%s\n' '{"kind":"set_drain","enabled":true}' > "$HOME/cursus-deployment/drain.json"
   /opt/cursus/current/venv/bin/cursus action --input "$HOME/cursus-deployment/drain.json"
   /opt/cursus/current/venv/bin/cursus status --deployment
   ```

3. Drain stops new admission/claims. Finish/reconcile existing work; the required
   switch state is `drain: true`, `unresolved_attempts: 0`, `queued_jobs: 0`, plus
   no pending container lifecycle entries on A. If drain stranded queued work,
   keep the old release, deliberately reopen to finish it, then drain again.
   Abandoning workflow ownership does not establish container termination.
4. Back up before incompatible code/schema changes. With services stopped and
   work drained, take a PostgreSQL custom-format dump and a consistent copy of
   B's artifact tree to the private backup destination. For example, on B:

   ```bash
   sudo systemctl stop cursus-control
   sudo -u cursus-control sh -c 'umask 077; pg_dump --format=custom --dbname="postgresql:///cursus?host=/var/run/postgresql" --file=/var/backups/cursus/pre-upgrade.dump'
   ```

   Use a unique backup name for each upgrade, preserve artifact/DB consistency,
   protect the backup as private data and transfer it off B. Verify restore in
   an isolated database/artifact directory before trusting it. Automated backup,
   retention and restore commands are not implemented (WP-19); do not treat the
   config's backup fields as an active backup service. Restart the old controller
   after the snapshot if you need it running for the activation drain check.
5. Prepare the new qualified role/image/profile/config release (§§8–10) and
   stage it on both hosts (§11.1 or §12.1–12.3). Do not rewrite queued frozen
   invocations to make new profiles match. New config bytes get a new stage.
6. With old controller running and drain verified, activate B, then A using
   §11.2's `--activate-existing --apply` commands. Even manually staged releases
   can use this guarded activation; this avoids bypassing migration/drain checks.
   Stop an old root/system runner explicitly before migrating to a user service.
7. Repeat §13 readiness checks. The controller intentionally stays drained after
   an upgrade. Reopen only after both hosts reconcile correctly:

   ```bash
   printf '%s\n' '{"kind":"set_drain","enabled":false}' > "$HOME/cursus-deployment/reopen.json"
   /opt/cursus/current/venv/bin/cursus action --input "$HOME/cursus-deployment/reopen.json"
   /opt/cursus/current/venv/bin/cursus status --deployment
   ```

### Rollback

Use the **previous exact commit and its matching saved config** with the same
`--activate-existing --apply` command on each host. The stage path includes the
config digest; supplying a modified config does not select the old stage.
Keep intake drained while diagnosing a failed switch. Read the installer output
to determine whether it already switched `current`; a failure does not promise
that the old service is still active.

A code symlink rollback is safe only with compatible applied migration history.
Migration 003 is present in this branch; older main does not understand it.
Returning to old main requires a matching database backup/restore boundary, not
just pointing `current` at old Python code. The installer refuses missing/changed
migration files before stopping the service. If safe matching code/config/data
cannot be established, remain drained and recover forward.

### Cleanup and recovery

Unknown or cleanup-pending containers retain resource and credential leases.
The browser reports reason/age; fix the underlying Podman/storage issue and let
Cursus retry confirmed stop/removal. Never delete the ledger, journal or auth
directories to manufacture spare capacity. Never run blanket `podman prune` or
kill every Python/Node process. Workspace deletion is queued durably; published
Git caches/images still need deliberate retention. A disk reserve is an admission
check, not a filesystem quota.

## 16. Troubleshooting

Read the applicable service's recent journal first. Record a sanitized error
code, time, host and release; never publish secrets or raw complete configs.

| Symptom | Check | Action |
| --- | --- | --- |
| `python3` cannot import `tomllib` | `python3 --version` | Use supported Ubuntu/Python, not a Python older than 3.12 |
| Script says unsupported OS | `/etc/os-release` | Use Ubuntu 26.04 for this installer; do not bypass the host check |
| Wrong source/dirty tree | `git rev-parse HEAD`, `git status --short` | Select the exact reviewed final commit; keep private config/wheels outside checkout |
| Remaining replacement markers | Local TOMLs and role tuples | Fill every field, with unquoted integers for numeric policies; do not mark nonexistent evidence qualified |
| Incomplete stage | Named path in installer error | Inspect retained stage and failed command; do not delete current/shared directories or overwrite immutable stages |
| Wheel unavailable/hash mismatch | Target Python/architecture and lock | Rebuild/retransfer matching wheelhouse; retain hash checking |
| Configuration fails to load | Private file modes/paths and journal | Ensure service account can traverse/read exact files, secrets are regular `0600`, schema is 2 |
| Role/prompt release mismatch | Final committed role release and staged bytes | Commit qualified role changes and stage a new clean release; do not edit installed files |
| Capability digest/image mismatch | Final capability `sha256sum`, image ID | Requalify changed bytes and update the matching committed role/config release |
| Insufficient credential concurrency | Provider ceiling vs domains vs measurements | Supply one disjoint measured domain per requested ceiling; do not share/copy rotating files or silently lower settings |
| `Failed to connect to bus` on A | Linger, `/run/user/UID/bus`, correct UID | Start the service account's user manager; recreate §7's function after reconnect |
| Podman rootless/subuid/cgroup error | §7 runtime checks | Repair host delegation/ranges through host policy; do not switch to root containers or mount a runtime socket |
| Image missing | `runner podman images --no-trunc` | Load the exact approved image as runner, not root; runtime will not pull |
| Provider auth works only outside container | Auth mount path, UID, HOME, keyring dependence | Qualify the actual directory-only native flow; a personal host login is not a container login |
| Verifier command/dependency missing | Image's absolute command and network-free check | Bake dependencies into a new qualified image; do not enable verifier network |
| PostgreSQL peer auth failure | Linux user, DB role, local socket DSN | Test §10.4 as `cursus-control`; preserve local auth policy, no remote DSN on A |
| Operator socket access denied | `id -nG`, socket group/mode | Reconnect after group change; do not make socket world-writable |
| Socket already exists | Old controller status/process | Stop/verify the old owner before removing only a proven stale configured socket; never unlink a live one |
| Website 403 / wrong host | Exact login, origin, Serve proxy | Use the canonical private HTTPS URL with intended Tailscale account; do not forge headers or expose loopback |
| Website form fails after restart | Browser session | Reload for fresh session/CSRF tokens; preserve request UUID if retrying |
| Runner unauthorized | Shared UUID/origin, bearer pairing | Check digest pairing through controlled secret tools; never print the bearer or paste it into browser |
| Runner waits despite spare ceiling | Memory/disk reserve, agent/verifier slice, lifecycle health | Fix actual resource/cleanup issue; ceilings are not guaranteed simultaneous capacity |
| Unknown attempt after disconnect | Phase/attempt and lifecycle state | Reconcile evidence and positively identified processes; no blind resubmit/relaunch |
| Upgrade refuses unresolved/queued jobs | `cursus status --deployment` | Finish old work under its original release, then drain; do not rewrite DB state |
| Rollback refuses migration history | Previous code/config/database set | Keep drained; restore a tested matching backup or recover forward |
| 429, auth denial, persistent vendor errors | Sanitized provider outcome and known retry layers | Stop affected provider workload, honor cooldown; do not rotate identities or loop retries |

## 17. Developer checks and project references

These checks use local fixtures and are separate from intended-host qualification.
From a source checkout with the §5 build environment:

```bash
"$HOME/cursus-build-env/bin/python" -m unittest discover -s tests/unit
"$HOME/cursus-build-env/bin/python" -m pip check
```

Integration tests need an **authorized disposable PostgreSQL 16+ database**.
The test role needs permission to create schemas; tests create/drop their own
random schemas. Never use production. For a new local peer-auth test database,
create a dedicated role matching your development Linux login and an isolated
owned database, then set the non-secret peer DSN, for example:

```bash
export CURSUS_TEST_DSN='postgresql:///cursus_test?host=/var/run/postgresql'
"$HOME/cursus-build-env/bin/python" -m unittest discover -s tests/integration
```

The example presumes that database/role were actually created and authorized;
missing DSN is an error, not a passing skipped test. Model boundaries use local
executable fixtures, not live provider inference. No frontend build is needed.

- [Operations details](ops/setup.md) and [historical runbook](ops/runbook.md).
  Older milestone-specific statements in the runbook are historical; this README
  and ADR 0009 describe the current schema-2/container deployment.
- [Qualification evidence and remaining live gates](tests/qualification.md).
- [Container acceptance matrix](docs/acceptance/container-execution.md).
- [Technical specification](docs/cursus-technical-specification-v0.1.2.md),
  [design](docs/cursus-design-document-v0.1.1.md),
  [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md).
- [Architecture decisions](docs/decisions/), including
  [container execution](docs/decisions/0009-container-execution.md),
  [artifacts/browser](docs/decisions/0007-m3-artifacts-and-browser.md).
- [Changelog](CHANGELOG.md), [dependency licenses](docs/dependency-licenses.md),
  [MIT license](LICENSE).

Public source contains no private host inventory or credentials. No release tag,
fixture result or successful install alone establishes live milestone acceptance.
