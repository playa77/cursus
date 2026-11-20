# Cursus

Cursus runs coding agents in isolated containers, verifies and reviews their
changes, and gives you a pull request through a private website.

## Quick install

**On each Ubuntu Server 26.04 machine, in your normal SSH terminal:**

```bash
curl -fsSL https://raw.githubusercontent.com/playa77/cursus/main/install.sh | bash
```

Run the **same script** on both servers. Choose **controller** on VPS-B
(database and website), and **worker** on VPS-A (agent containers). You do not
need to clone this repository, create `~/cursus-source`, install Python packages,
prepare a wheelhouse, or change directory first. The installer handles those
steps. It asks before changing the host and uses `sudo` when necessary.

Fresh installation does not ask for a repository, branch, test command or GitHub
publisher token. Both hosts start with no repositories enrolled. You can leave
Cursus idle for two weeks or longer and [enroll a repository later](#enroll-a-repository-and-its-checks).
Normal server maintenance and native account session renewal still apply.

If your server says `curl: command not found`, install it first:

```bash
sudo apt-get update
sudo apt-get install --yes curl
```

Start on **A (worker) first**. The installer builds its execution image and
installs **Claude Code, Codex CLI, Antigravity and pi** in it. It then opens each
of those installed apps and reminds you to complete its native login. Use your
normal subscriptions/accounts. Cursus subsequently runs those same installed
apps with that same persistent native login state.

You do **not** supply an image, write `capabilities.toml`, copy login files or
provide replacement provider API keys. After login, the installer asks permission
for a bounded set of native checks and generates the capability configuration.
At the end it prints a **pairing code**. Run the same installer on **B
(controller)** and paste that code when asked. The code contains deployment
metadata and the bearer digest, never native credentials or the bearer token.

To inspect the script before running it, use this equivalent workflow, which
also detects a failed download before any script executes:

```bash
curl -fL --connect-timeout 15 --max-time 120 https://raw.githubusercontent.com/playa77/cursus/main/install.sh -o /tmp/cursus-install.sh
less /tmp/cursus-install.sh
bash /tmp/cursus-install.sh
```

Press `q` to leave `less`. To preview without making changes or additional
network requests:

```bash
bash /tmp/cursus-install.sh --host controller --dry-run
bash /tmp/cursus-install.sh --host worker --dry-run
```

Downloading the script itself is still a network request. You can run an already
downloaded script from **any directory**, including an otherwise empty home.

## What the installer does

1. Asks which host you are installing and whether to proceed. Interactive
   questions use your terminal, so `curl | bash` does not consume the answers.
2. Checks Ubuntu 26.04, installs bootstrap tools, creates the source checkout if
   absent, and selects the requested source revision. Existing work is never reset.
3. Prepares the stable service account, private directories, PostgreSQL on B or
   rootless Podman/user manager on A. On A, installs all four native tools,
   guides their native logins, checks the installed interfaces with your approved
   budget, and generates the image/profile configuration. On B, imports that
   generated metadata from A’s pairing code. Generates the runner bearer
   without printing it. Fresh setup enrolls no repositories and requests no
   GitHub publisher credentials.
4. Downloads hash-locked dependencies automatically (or uses your supplied
   offline wheelhouse), builds and stages an immutable Python release/config.
5. Validates and activates using the existing drain, migration and runtime
   checks. An installation failure prints **INSTALLATION INCOMPLETE**; a staged
   release is not reported as a running service.

Guided controller setup creates a separate, content-addressed local Git release
of the qualified roles and committed prompts. It pins that commit in the control
config. It does not ask you to edit installed source or commit host settings to
GitHub. Existing configurations and secrets are preserved, not overwritten.

The script does not silently enroll Tailscale, change a firewall or spend money on
model checks. It asks for your check budget and confirmation after native login. Those account- and policy-specific
steps are described below. [ADR 0010](docs/decisions/0010-unified-installer.md)
records the bootstrap boundary; [ADR 0011](docs/decisions/0011-native-install-and-login.md)
corrects its earlier external-profile prerequisite.

## What you need to answer

The installer reads machine facts itself. It runs one bounded
`tailscale status --json` query per host, lists discovered peers/accounts, and
asks you to select their roles by number. You do not type a Tailscale URL,
worker DNS name, login email, runner UUID, image ID, Podman version, capability
digest, native-state directory, or runner bearer token/digest.

Before starting the worker, enroll **both servers** in the same Tailscale network
and enable MagicDNS. The controller does not need Cursus installed yet. On each
server, `sudo tailscale up` starts the native enrollment flow if needed. If
Tailscale is missing, follow its [Linux installation guide](https://tailscale.com/docs/install/linux).
If discovery fails or access rules hide the controller, correct enrollment or
visibility and rerun; the installer does not ask you to transcribe missing facts.

| Question | What it means and how to answer |
| --- | --- |
| This server's role | Choose `worker` on A (AI tools and containers); later choose `controller` on B (website and database). These are deployment choices, not hostname conventions. |
| Controller selection on A | Select B by number from the discovered Tailscale DNS names. The installer constructs its HTTPS address. Do not select A. |
| Operator selection on B | Select the discovered Tailscale account you authorize to operate the website. Use the account you will sign in with from your browser. The machine owner's identity alone does not authorize website access. |
| Worker pairing code on B | Copy the code printed by A's installer. It transfers deployment metadata, including the worker DNS name and bearer digest. No native credentials or bearer secret are included. B checks that the code names its own Tailscale address. Older codes require a numbered worker selection. |
| Session ceilings | Choose pi sessions from 1–4 and Claude Code, Codex and Antigravity sessions independently from 1–2. These are authorized concurrency ceilings, not measured provider capacity. Each slot has an independent native login domain. B imports A's choices. |
| Total execution budget | Set `containers.budget.memory_mb`, `cpu_millis` and `pids`: total scheduled memory, CPU and process/thread allowances. The installer displays detected RAM, cores and free runner disk. Reserve resources for the host and verifier; observed free resources alone cannot determine workload requirements. |
| Host reserves | `host_reserve_mb` leaves RAM for Ubuntu and host services. `host_reserve_cpu_millis` leaves CPU for them. Total execution budget plus reserves must fit the worker. |
| Per-container limits | Under `containers.resources.agent` and `.verifier`, choose limits for **one** container: RAM (`memory_mb`), CPU (`cpu_millis`), processes/threads (`pids`), temporary files (`tmp_mb`) and disposable home (`home_mb`). Use requirements or measurements from representative jobs. Temporary/home storage is memory-backed; persistent native login state is separate. |
| Units | Enter positive whole numbers. 1024 MiB = 1 GiB; 1000 CPU millis = one core. `pids` counts processes and threads, not bytes. |
| Disk reserve | `disk_reserve_mb` is the minimum free worker disk before Cursus stops launching containers. Choose headroom for repositories, images, logs and Ubuntu, using the detected free disk as context. |
| Native logins | When each installed app opens, complete its own login flow with the account you authorize. For pi, use `/login` and choose the intended OpenCode Go provider. Complete each requested slot, then exit the app. No login files or replacement API keys are requested. |
| Model and pi provider choices | Choose and save the default model in each installed app’s native model selector; choose pi’s provider there too. Setup reads only those selected fields from its own persistent settings inside the execution container. You do not retype IDs. If no saved selection exists, setup opens the app for you to choose and save one. |
| Native-check budget | Enter the maximum charge you authorize, including currency, then explicitly approve the displayed invocation/time limits. This records consent; it does not enforce a provider billing cap. Checks stop on failure without installer inference retries. |
| Off-host backup destination on B | Enter the destination used by your independently managed backup procedure, for example a private backup server/path. Cursus records it but does not provision, copy or schedule backups. Choose and verify that procedure separately. |

The controller DNS name can exist before its website is ready. Constructing
`https://` plus that name does **not** prove HTTPS is configured or reachable.
Follow [the private HTTPS readiness steps](#start-private-https-and-check-the-whole-system)
to enable Tailscale Serve and check the deployed service. On B,
`tailscale serve status --json` reports the configured Serve endpoints;
`tailscale status --json` reports B's own name in `Self.DNSName` even before
Serve is configured. The installer reads the latter automatically.

If you already have complete configs, use the same entry point without answering
the worksheet questions:

```bash
bash /tmp/cursus-install.sh --host controller --config /absolute/control.toml
bash /tmp/cursus-install.sh --host worker --config /absolute/runner.toml
```

These two commands belong on **their respective machines**, not both on one
server. Relative config paths are resolved from your current directory.

Useful options:

| Option | Purpose |
| --- | --- |
| `--host controller` / `--host worker` | Skip host-selection question |
| `--ref FULL_COMMIT` | Obtain a specific reviewed source revision |
| `--source-dir /absolute/path` | Choose where source is obtained; no directory need exist yet |
| `--wheelhouse /absolute/wheels` | Use offline locked dependencies instead of downloading |
| `--native-only` | On A, install tools, guide login and generate config/pairing output without staging Cursus services |
| `--stage-only` | Prepare an immutable release without switching or starting services |
| `--activate-existing --config /absolute/config.toml` | Activate the exact previously staged commit/config |
| `--non-interactive --yes --host ... --config ...` | Unattended host installation with all prerequisites already provisioned |
| `--dry-run` | Print a no-change plan without requiring a checkout or configuration |
| `--help` | Full option list |

A downloaded installer fast-forwards a clean default checkout so rerunning it
uses the current installer, rather than an older helper. Dirty/diverged default
checkouts are preserved and a separate checkout is obtained. Explicit
`--source-dir` checkouts are never reset. To select an exact new release, use
`--ref FULL_COMMIT` and a new `--source-dir /absolute/new-checkout`. For activation
of an old stage, select its exact source commit and saved host configuration.

A supplied configuration must be complete and use private regular secret files.
Unattended mode never reads a token from a shell argument or falls back to a
prompt. The older `deploy/setup-controller.sh` and `deploy/setup-worker.sh` remain
compatibility entry points for existing automation; **new installations use only
`install.sh`**.

## Finish the installation

On B, establish the private Tailscale network as described under
[private network](#private-network), then start Serve after the backend is active:

```bash
sudo tailscale serve --bg http://127.0.0.1:8787
tailscale serve status
sudo systemctl status cursus-control --no-pager
sudo /opt/cursus/current/venv/bin/cursus status --deployment
```

On A, inspect its service through the stable account's user manager:

```bash
CURSUS_RUNNER_UID=$(id -u cursus-runner)
sudo runuser -u cursus-runner -- env XDG_RUNTIME_DIR="/run/user/$CURSUS_RUNNER_UID" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$CURSUS_RUNNER_UID/bus" systemctl --user status cursus-runner --no-pager
```

Open B's exact private HTTPS URL on your PC while signed in to Tailscale.
Expect the Cursus overview and fresh authenticated runner contact. A service
being `active` is not proof that provider login, native tool restrictions,
resource containment or end-to-end publication passed. Use the
[whole-system checks](#start-private-https-and-check-the-whole-system), then
[first task](#submit-and-follow-your-first-task).

**Trouble with the reported `cd` error?** You do not need that command for the
scripted path. Run the installer above directly from `devops@server:~$`. For a
manual install, the [source acquisition step](#prepare-both-servers-and-the-source-release)
explicitly creates the checkout before entering it.

## Detailed reference and manual installation

The rest of this README is the reference/manual path. **You do not have to perform
all of it before running the installer.** Scripted users should consult the
sections needed for their network/provider setup, configuration choices and
verification. Manual users follow the preparation/configuration sections in
order, then [manual installation](#install-manually).

- [Machines and terminology](#understand-the-machines-and-commands)
- [Deployment information](#collect-the-information-you-need)
- [Manual server/source preparation](#prepare-both-servers-and-the-source-release)
- [Private network](#private-network)
- [Manual Python dependencies](#prepare-the-python-dependencies)
- [Manual accounts and storage](#prepare-accounts-and-persistent-storage)
- [Native CLI prerequisites](#native-cli-prerequisites)
- [Capability measurement and role release](#measure-capabilities-and-pin-the-role-release)
- [Private configuration and secrets](#private-configuration-and-secrets)
- [Manual installation](#install-manually)
- [Whole-system checks](#start-private-https-and-check-the-whole-system)
- [First task](#submit-and-follow-your-first-task)
- [Operations, upgrade and rollback](#operate-upgrade-roll-back-and-recover)
- [Troubleshooting](#troubleshooting)
- [Developer checks and references](#developer-checks-and-project-references)

## Understand the machines and commands


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

## Collect the information you need


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
| Provider accounts and selected CLI builds | All four providers; verify plan access and supported unattended login first |
| Capacity, resource and disk policy | Choose the explicit ceilings and budgets in [private configuration and secrets](#private-configuration-and-secrets); they are not inferred from advertised RAM |
| Provider test budget | Decide maximum invocations, elapsed time, concurrency and money before any live prompt |
| Backup destination and retention | A private location independent of B; backup scheduling/restore automation is not supplied yet |

Repository details, check commands and publisher tokens are needed only when
you later [enroll a repository](#enroll-a-repository-and-its-checks).

You will need free storage for PostgreSQL, immutable artifacts, container images,
Git caches and workspaces. Run `df -h / /var /opt` on both servers. There is no
validated fixed disk-size recommendation; choose a reserve and monitor actual
use. Keep administrative recovery access through your provider while changing
network settings. Do not replace an existing firewall policy blindly.

## Prepare both servers and the source release


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
checkout for the role customization in [measure capabilities and pin the role release](#measure-capabilities-and-pin-the-role-release). Do not commit secrets or machine
inventory. Re-run `git rev-parse HEAD` after that customization: the **final**
commit, not the original public commit, becomes `CURSUS_RELEASE` for installation.
Use that same final commit on both hosts.

If you reconnect later, variables from the old terminal are gone. Return with
`cd "$HOME/cursus-source"`, then set `CURSUS_RELEASE=$(git rev-parse HEAD)`.
Never set it before checking that you are in the intended repository.

## Private network


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
tailnet, Funnel is public. Serve is started only after B's backend works in [start private https and check the whole system](#start-private-https-and-check-the-whole-system).
See [the Serve documentation](https://tailscale.com/docs/features/tailscale-serve)
for its enrollment and private HTTPS behavior.

## Prepare the Python dependencies


Do this on **each target host**, or on a matching OS/architecture/Python machine
and transfer its wheelhouse to that host. A wheelhouse prepared for a different
Python or CPU architecture may not work.

From `~/cursus-source`:

```bash
python3 -m venv "$HOME/cursus-build-env"
"$HOME/cursus-build-env/bin/python" -m pip download --require-hashes --only-binary=:all: --dest "$HOME/cursus-deployment/wheels" -r requirements.lock
"$HOME/cursus-build-env/bin/python" -m pip install --no-index --find-links "$HOME/cursus-deployment/wheels" --require-hashes -r requirements.lock
PIP_NO_INDEX=1 "$HOME/cursus-build-env/bin/python" -m build --wheel --no-isolation
"$HOME/cursus-build-env/bin/python" -m pip install --no-index --no-deps dist/cursus-0.6.0-py3-none-any.whl
"$HOME/cursus-build-env/bin/python" -m pip check
"$HOME/cursus-build-env/bin/cursus" --version
```

Expected: dependency download/install succeeds, `pip check` reports no broken
requirements and the version is `cursus 0.6.0`. The lock includes the build tools;
no global pip install is needed. If a compatible wheel is missing, stop and
prepare a reviewed wheelhouse for the target; do not remove hash checking.

This does not log in to any model provider or start Cursus. Python dependency
installation and native agent installation are separate tasks.

## Prepare accounts and persistent storage


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

The unified installer creates them automatically. If either already exists, inspect
its ownership and privileges with your database administrator; do not drop it or
continue against an unrelated database. Use local peer authentication: Linux
`cursus-control` connects as database `cursus-control` with no password argument.

## Native CLI prerequisites

The installer provides the native image recipe in
[`deploy/native/Containerfile`](deploy/native/Containerfile). It installs the
native apps, records their resolved versions/digests, and pins the completed
image ID. The image contains no login credentials. Native login happens afterward
under the rootless runner identity, with isolated persistent state directories.
There is no separate image or measured-profile prerequisite for normal setup.

### Complete the four login prompts on A

1. **Claude Code:** the installer runs `claude auth login`. Choose your intended
   account/subscription and complete the displayed browser instructions.
2. **Codex CLI:** it runs `codex login --device-auth`. Open the displayed URL on
   your PC, sign in with ChatGPT and enter the displayed device code.
3. **Antigravity:** it opens `agy` in its private container session. Follow the
   remote-login URL/code instructions and exit after signing in.
4. **pi:** it opens `pi`. Type `/login`, select the agreed OpenCode Go provider,
   complete enrollment, then exit. Select the intended model in the native UI.

Do not enable optional plugins/extensions or import another app’s configuration
during onboarding. The image already contains the four required tools. If you
chose more than one simultaneous session for a provider, login is repeated for
each isolated domain. Credentials are not copied between domains. The native
clients own their login/refresh state; Cursus reuses it in place.

Antigravity's Secret Service runs inside its container. Its private keyring state
persists in that domain; the keyring unlock is unattended and uses an empty
password. Host file ownership protects this state, not encryption against the
server administrator. No host keyring or host D-Bus socket is mounted.

### Resume or install the native tools without starting Cursus

After obtaining source, the same installer supports:

```bash
bash install.sh --host worker --native-only
```

This prepares the native installations, opens the login prompts, generates the
capability/configuration files, and prints the pairing code. It does not stage
or start Cursus services. First-time native setup requires your SSH terminal;
unattended mode is for already provisioned deployments.

### Manual image build

After the manual accounts/source steps, from the source checkout on A:

```bash
runner podman build --pull=missing --tag localhost/cursus-native:manual deploy/native
runner podman image inspect localhost/cursus-native:manual --format '{{.Id}}'
```

The recipe installs Node/build tools and the actual native distributions. The
installer normally copies the build context to runner-owned private storage so
it is accessible even if your administrator home is private; for a direct manual
build, place these three build files in a directory readable/traversable by the
runner. Never loosen permissions on your whole home or put credentials in the
build context. Verification tools/dependencies for your enrolled repository must
also exist in the image; verifiers execute without network.

Manual native authentication uses the same supported vendor commands above,
inside the image with persistent native-state subdirectories and a disposable
HOME. The `--native-only` path performs this container plumbing and lifetime
tracking for you; use it when you do not need to administer Podman manually.
Existing manually maintained qualified images/profiles remain an advanced option.

## Measure capabilities and pin the role release

`capabilities.toml` is generated **by setup from the installed apps**. The normal
installer never asks you to author it or supply an absolute path to one.

After the native logins, setup requests a charge authorization and confirmation
for at most `2 × total native login domains + 1` CLI invocations: two checks per
domain in separate containers, plus the read-only pi scout transport. Each has a
120-second native timeout, 10-second kill grace, and 140-second supervisor bound;
there are no installer inference retries. Native provider-side retries/request
counts and billable cost are not an enforceable provider cap. Stop/retry decisions
remain explicit after failure.

The checks use the logged-in native apps, validate installed options and terminal
JSON/RPC responses, and verify login state persists after the first container is
removed. pi RPC stdin remains open until its terminal turn. The generated profile
records `native-checked`; this describes those actual checks, **not** completed
maximum-concurrency refresh, resource-isolation or M3 acceptance. Full intended-host
qualification remains recorded separately in [qualification](tests/qualification.md).

Setup records exact app versions, executable hashes, image ID, model/reasoning
settings, native invocation arguments and observed check digests. It persists
only sanitized check metadata, not raw credentials or login output. A changed
image/native interface needs new checks. A failed login or unknown required option
fails visibly; it does not generate successful evidence or ask you to invent flags.

On A the generated capability file is content-addressed under
`/etc/cursus/runner/capabilities-<digest>.toml`. The pairing code brings the same
non-secret profile bytes to B. B automatically creates and pins its local role/
prompt Git release. Native credentials remain on A. Supplied complete configs and
legacy manually qualified role/profile releases are still supported for advanced
and offline deployment; they are not first-time setup requirements.

## Private configuration and secrets


### Copy and edit configuration

The guided installer generates these files and pins the native profile for you.
The following template-editing steps are the advanced manual alternative. Do not
replace working generated files with blank worksheets.

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
| B service | `role_release_commit` | The pinned local role commit generated from A’s pairing metadata, or your explicit manual role release |
| B runner | `id`, `tailnet_node` | Shared runner UUID and actual A tailnet node |
| B backup | `off_host_destination` | Your private backup destination; this field does not schedule backups |
| A service | `origin`, `runner_id` | Same B HTTPS origin and runner UUID |
| A service | `capabilities_digest` | SHA-256 of the generated native capability file |
| A containers | `version`, `image` | Exact installed Podman `5.x.y` and the full image ID built by setup |
| Both | `capacity` | Identical integer ceilings, as below |
| Both | `repositories` | Identical owner/name/object format, full allowed target refs and checks |
| A containers | `credentials` | Exactly one qualified domain per configured simultaneous provider invocation |

Leave `listen_host = "127.0.0.1"`, port 8787, socket and service user paths as
shown unless you also deliberately adapt the service units and all references.
Schema 2 is required. Keep the template's other limits initially; they bound
requests, retries and artifacts rather than authorizing spending.

### Choose capacity and resources explicitly

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

### Enroll a repository and its checks

This is optional work **after installation**, when you have a repository you
want Cursus to use. Skip this section while leaving it idle. Native login and
resource configuration remain installation steps; repository authority is separate
([ADR 0013](docs/decisions/0013-idle-installation.md)).

| Value | What it means and where to get it |
| --- | --- |
| Owner and repository name | Choose the repository Cursus may work on. For its GitHub page `https://github.com/alice/project`, owner is `alice` and name is `project`. It need not be the Cursus installer repository. |
| Allowed target refs | Choose target branches from the repository's branch selector. Write full refs, such as `refs/heads/main`. This permits targeting that branch; it does not permit direct publication to it. |
| Verification command | Use the repository's documented test command or CI workflow. Write a JSON/TOML argument list with an absolute executable path inside the execution image, not a shell command. The tools and dependencies must exist there. |
| Check ID and phase check IDs | Give the command a local ID, such as `unit`, and include that ID in `phase_check_ids`. These are your configured names, not GitHub check-run IDs. |
| Working directory and timeout | `cwd` is a repository-relative directory, usually `.`. `timeout_seconds` bounds the check; choose it for that workload. |
| GitHub publisher token on A | Create a dedicated fine-grained token in GitHub Settings → Developer settings → Personal access tokens. Select the enrolled repository and grant Contents read/write and Pull requests read/write. Obtain organization approval if needed. Supply it only through the hidden credential prompt when staging A's enrolled config, or the private files described below. |

For a guided installation, edit the saved settings on A at
`/etc/cursus/runner.toml` and on B at `/etc/cursus/control.toml`. These are inputs
for a new staged configuration; do not edit the active release under
`/opt/cursus/current`. Remove the top-level `repositories = []` line, then append
the **same** enrollment on both hosts. For example, only if this is the actual
repository and test command you authorize:

```toml
[[repositories]]
owner = "alice"
name = "project"
object_format = "sha1"
allowed_target_refs = ["refs/heads/main"]
phase_check_ids = ["unit"]

[[repositories.checks]]
id = "unit"
argv = ["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests/unit"]
cwd = "."
timeout_seconds = 300
```

For a manually prepared config, replace its entire example enrollment with the
chosen repository. Leave existing enrollments intact if adding another one.
Do not put `repositories = []` inside a `[service]` or other table. A check's `argv[0]`
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

Apply enrollment using the [existing guarded upgrade procedure](#drain-and-upgrade):
drain and reconcile the deployment, stage the matching configs on both hosts,
activate B then A, verify readiness, and reopen admission. When staging A with
`--config /etc/cursus/runner.toml --stage-only`, the installer requests the
publisher token through hidden input if its private files are missing. It
preserves existing credential files. B never receives the publisher token.
For a new config, stage it before using `--activate-existing`; that flag selects
the exact source/config stage, so changing TOML alone does not change the running
service. There is currently no browser enrollment editor.

### Create the runner bearer without displaying it

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

### Provision publication credentials and capability file

Publisher credentials are needed only for an enrolled repository. Skip their
creation while `repositories = []`; the capability file is still required for
native tool configuration. An idle install does not need GitHub access.

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

## Install manually


This is the alternative to the unified installer above. It preserves the same release layout, private
config and systemd boundaries. Complete the manual account, image, profile and configuration sections first, including the manual DB
creation. Run on **both** hosts unless a step says otherwise.

### Build the immutable release

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
sudo "$CURSUS_STAGE/venv/bin/python" -m pip install --no-index --no-deps "$CURSUS_STAGE/wheels/cursus-0.6.0-py3-none-any.whl"
sudo "$CURSUS_STAGE/venv/bin/python" -m pip check
sudo install -m 600 -o "$CURSUS_SERVICE_USER" -g "$CURSUS_SERVICE_USER" "$CURSUS_CONFIG" "$CURSUS_STAGE/config.toml"
sudo "$CURSUS_STAGE/venv/bin/cursus" --version
```

Expected: version 0.6.0, no missing requirements. Root owns source/venv; the
service user may read them but must not edit installed code.

### Validate before switching

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

### Install B's unit and A's resource slices

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

### Switch and start (new installation)

The following commands are for **first installation only**. On both hosts,
verify `/opt/cursus/current` does not already exist. For an upgrade, use [operate, upgrade, roll back and recover](#operate-upgrade-roll-back-and-recover)'s
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

Set up Serve in [start private https and check the whole system](#start-private-https-and-check-the-whole-system) before starting **A**:

```bash
runner systemctl --user daemon-reload
runner systemctl --user start cursus-execution.slice cursus-execution-agents.slice cursus-execution-verifier.slice
runner systemctl --user enable --now cursus-runner
runner systemctl --user status cursus-runner --no-pager
```

## Start private HTTPS and check the whole system


### Check B locally, then enable Serve

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

### Confirm A's authenticated contact

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

### Acceptance checklist

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
- The authorized end-to-end task in [submit and follow your first task](#submit-and-follow-your-first-task) produces independent checks/review and a
  PR at the exact verified head without modifying/merging the target branch.
- A bounded stop/restart/recovery exercise retains unknown ownership until real
  stop/removal is confirmed; no uncertain execution is automatically relaunched.

The detailed [qualification checklist](tests/qualification.md) and
[container finding matrix](docs/acceptance/container-execution.md) define the
remaining M3-end qualification. Keep an item pending when it has not been run.

## Submit and follow your first task


Use an expendable **enrolled GitHub repository** and a small clearly bounded
change. This step invokes paid/subscription providers and writes GitHub refs/PRs;
first establish the call/time/concurrency/cost budget and termination mechanism
from [measure capabilities and pin the role release](#measure-capabilities-and-pin-the-role-release). Do not use a production task as an authentication experiment.

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

## Operate, upgrade, roll back and recover


### Daily operations

| Task | B | A (with the [prepare accounts and persistent storage](#prepare-accounts-and-persistent-storage) `runner` function) |
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
5. Prepare the new qualified role/image/profile/config release ([native CLI prerequisites](#native-cli-prerequisites) through [configuration](#private-configuration-and-secrets)) and
   stage it on both hosts ([the unified installer](#quick-install) or [manual staging](#install-manually)). Do not rewrite queued frozen
   invocations to make new profiles match. New config bytes get a new stage.
6. With old controller running and drain verified, activate B, then A using
   the same installer with `--host controller` on B or `--host worker` on A,
   `--config /absolute/config.toml --activate-existing`. Even manually staged releases
   can use this guarded activation; this avoids bypassing migration/drain checks.
   Stop an old root/system runner explicitly before migrating to a user service.
7. Repeat [start private https and check the whole system](#start-private-https-and-check-the-whole-system) readiness checks. The controller intentionally stays drained after
   an upgrade. Reopen only after both hosts reconcile correctly:

   ```bash
   printf '%s\n' '{"kind":"set_drain","enabled":false}' > "$HOME/cursus-deployment/reopen.json"
   /opt/cursus/current/venv/bin/cursus action --input "$HOME/cursus-deployment/reopen.json"
   /opt/cursus/current/venv/bin/cursus status --deployment
   ```

### Rollback

Use the **previous exact commit and its matching saved config** with the same
`--activate-existing` installer command on each host. The stage path includes the
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

## Troubleshooting


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
| Insufficient credential concurrency | Provider ceiling vs domains vs measurements | Complete native login for each requested isolated domain; do not share/copy rotating files or bypass provider limits |
| `Failed to connect to bus` on A | Linger, `/run/user/UID/bus`, correct UID | Start the service account's user manager; recreate [prepare accounts and persistent storage](#prepare-accounts-and-persistent-storage)'s function after reconnect |
| Podman rootless/subuid/cgroup error | [prepare accounts and persistent storage](#prepare-accounts-and-persistent-storage) runtime checks | Repair host delegation/ranges through host policy; do not switch to root containers or mount a runtime socket |
| Image missing | `runner podman images --no-trunc` | Load the exact approved image as runner, not root; runtime will not pull |
| Provider auth works only outside container | Auth mount path, UID, HOME, keyring dependence | Use the installer’s native login prompts for that image/domain; Antigravity’s private keyring runs inside the container |
| Verifier command/dependency missing | Image's absolute command and network-free check | Bake dependencies into a new qualified image; do not enable verifier network |
| PostgreSQL peer auth failure | Linux user, DB role, local socket DSN | Test [private configuration and secrets](#private-configuration-and-secrets) as `cursus-control`; preserve local auth policy, no remote DSN on A |
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

## Developer checks and project references


These checks use local fixtures and are separate from intended-host qualification.
From a source checkout with the [prepare the python dependencies](#prepare-the-python-dependencies) build environment:

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
