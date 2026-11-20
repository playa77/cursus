#!/usr/bin/env bash
# Cursus installer entry point, revision 2026-11-20-r5. See ADR 0010.
set -euo pipefail
trap 'printf "Cursus bootstrap failed at line %s. No success is implied; inspect the error above.\n" "$LINENO" >&2' ERR

usage() {
  cat <<'HELP'
Usage: bash install.sh [options]
       curl -fsSL URL/install.sh | bash -s -- [options]

One entry point for both Ubuntu 26.04 hosts. With no options, asks which
host to install, prepares it, and guides configuration before staging/startup.

  --host controller|worker  B (database/website) or A (containers)
  --ref REF                Branch/tag/full commit to obtain (default: main)
  --source-dir PATH        Checkout location (default: $HOME/cursus-source)
  --config PATH            Existing complete private host TOML (optional)
  --wheelhouse PATH        Use offline locked dependencies (optional)
  --native-only            Worker: install native apps, login and prepare config only
  --stage-only             Stage without switching or starting services
  --activate-existing      Activate the exact already staged commit/config
  --non-interactive        Require --host, --config and --yes; no prompts
  --yes                    Apply host/package changes without initial prompt
  --dry-run                Print plan; no network, files, packages or services
  --help                   Show this help

Without --wheelhouse, downloads hash-locked Python wheels automatically.
Worker setup installs Claude Code, Codex CLI, Antigravity and pi, guides their
native logins, then requests a budget before native checks. It generates its
capability file; you do not supply a prequalified image or profile. Host firewall
and Tailscale enrollment remain explicit operator steps.
HELP
}

host= ref=main source_dir= config= wheelhouse= dry_run=0 yes=0 noninteractive=0
native_only=0 stage_only=0 activate_existing=0 explicit_source=0 explicit_ref=0
while (($#)); do
  case "$1" in
    --host|--ref|--source-dir|--config|--wheelhouse)
      if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
        printf 'Missing value for %s\n' "$1" >&2; exit 2
      fi
      case "$1" in
        --host) host=$2;;
        --ref) ref=$2; explicit_ref=1;;
        --source-dir) source_dir=$2; explicit_source=1;;
        --config) config=$2;;
        --wheelhouse) wheelhouse=$2;;
      esac
      shift 2;;
    --dry-run) dry_run=1; shift;;
    --yes) yes=1; shift;;
    --non-interactive) noninteractive=1; shift;;
    --native-only) native_only=1; shift;;
    --stage-only) stage_only=1; shift;;
    --activate-existing) activate_existing=1; shift;;
    --help|-h) usage; exit 0;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2;;
  esac
done
if [[ -n "$host" && "$host" != controller && "$host" != worker ]]; then
  printf '%s\n' '--host must be controller or worker.' >&2; exit 2
fi
if [[ "$ref" == -* || "$ref" == *$'\n'* ]]; then
  printf '%s\n' 'Invalid --ref.' >&2; exit 2
fi
if ((native_only && (stage_only || activate_existing))) || { ((native_only)) && [[ "$host" == controller ]]; }; then
  printf '%s\n' '--native-only requires a worker and conflicts with staging/activation options.' >&2; exit 2
fi
if ((stage_only && activate_existing)); then
  printf '%s\n' '--stage-only and --activate-existing conflict.' >&2; exit 2
fi
source_dir=${source_dir:-"$HOME/cursus-source"}
# A local checkout works from any cwd. A piped script has no local source tree.
local_root=
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  local_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  [[ -f "$local_root/deploy/setup.py" ]] || local_root=
fi
if [[ -n "$local_root" ]] && (( !explicit_source && !explicit_ref )); then source_dir=$local_root; fi
if ((dry_run)); then
  printf 'Cursus dry-run: NO changes or network requests.\n'
  printf 'Host: %s; source: %s; requested revision: %s\n' "${host:-ask controller or worker}" "$source_dir" "$ref"
  printf 'Plan: obtain source if absent; install Ubuntu prerequisites; prepare stable account/storage;\n'
  printf 'guide private config; prepare hash-locked wheels (or use supplied wheelhouse);\n'
  if ((native_only)); then
    printf 'install native apps, guide login, generate worker config and pairing output; no service staging.\n'
    exit 0
  fi
  printf 'validate release/config; stage immutable release; %s.\n' "$([[ $stage_only == 1 ]] && echo 'leave services unchanged' || echo 'validate and activate with drain/migration guards')"
  printf 'Worker plan includes building the native image, four guided logins and budgeted checks; controller consumes the generated pairing code.\n'
  exit 0
fi
if ((noninteractive)) && { [[ -z "$host" || -z "$config" ]] || ((!yes)); }; then
  printf '%s\n' '--non-interactive requires --host, --config and --yes.' >&2; exit 2
fi
if ((!noninteractive)); then
  # curl occupies stdin; all questions and sudo authentication use the terminal.
  if ! { exec 3<>/dev/tty; } 2>/dev/null; then
    printf '%s\n' 'No terminal. Download the script and run it in SSH, or supply --non-interactive --host ... --config ... --yes.' >&2; exit 2
  fi
  if [[ -z "$host" ]]; then
    printf '\nChoose the role of THIS server.\n  worker     Server A: runs the AI tools and task containers. Install this first.\n  controller Server B: runs the database and website. Requires the worker pairing code.\nEnter worker or controller: ' >&3
    read -r host <&3
    [[ "$host" == controller || "$host" == worker ]] || { printf 'Choose controller or worker.\n' >&2; exit 2; }
  fi
  if ((!yes)); then
    printf 'Install Cursus %s on this server? This obtains source and installs host packages/accounts/storage. [y/N] ' "$host" >&3
    read -r answer <&3
    [[ "$answer" == y || "$answer" == Y ]] || { printf 'Cancelled; no changes made.\n'; exit 0; }
  fi
fi
if [[ ! -r /etc/os-release ]] || ! ( . /etc/os-release; [[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] ); then
  printf 'This installer requires Ubuntu Server 26.04. No packages changed.\n' >&2; exit 1
fi
privilege=()
if (( EUID != 0 )); then
  command -v sudo >/dev/null || { printf 'Install sudo or run as an authorized administrator.\n' >&2; exit 1; }
  sudo -v
  privilege=(sudo)
fi
printf '[1/5] Preparing bootstrap tools...\n'
"${privilege[@]}" apt-get update
"${privilege[@]}" apt-get install --yes --no-install-recommends git python3 python3-venv ca-certificates
printf '[2/5] Obtaining source (no pre-existing checkout required)...\n'
resolve_ref() {
  git -C "$source_dir" rev-parse --verify "$ref^{commit}" 2>/dev/null ||
    git -C "$source_dir" rev-parse --verify "refs/remotes/origin/$ref^{commit}" 2>/dev/null
}
# Re-running the downloaded installer must not keep executing an older helper.
# Only fast-forward a clean default checkout; preserve dirty/diverged work.
if [[ -z "$local_root" ]] && ((!explicit_source)) && [[ -e "$source_dir" ]]; then
  if [[ ! -L "$source_dir" && -d "$source_dir/.git" ]] &&
     [[ -z "$(git -C "$source_dir" status --porcelain)" ]]; then
    git -C "$source_dir" fetch --no-tags https://github.com/playa77/cursus.git "$ref"
    wanted=$(git -C "$source_dir" rev-parse --verify 'FETCH_HEAD^{commit}')
    if git -C "$source_dir" merge-base --is-ancestor HEAD "$wanted"; then
      git -C "$source_dir" -c core.hooksPath=/dev/null checkout --detach "$wanted"
      ref=$wanted
    else
      printf 'Preserving diverged default checkout; obtaining a separate release.\n'
      source_dir=$(mktemp -d "$HOME/cursus-installer.XXXXXXXX")/source
    fi
  else
    printf 'Preserving existing default directory/work; obtaining a separate release.\n'
    source_dir=$(mktemp -d "$HOME/cursus-installer.XXXXXXXX")/source
  fi
fi
if [[ -e "$source_dir" ]]; then
  [[ ! -L "$source_dir" && -d "$source_dir/.git" || -n "$local_root" && "$source_dir" == "$local_root" ]] || {
    printf 'Refusing to overwrite %s; choose --source-dir with a new path.\n' "$source_dir" >&2; exit 1;
  }
  if ((explicit_ref)); then
    actual=$(git -C "$source_dir" rev-parse HEAD)
    wanted=$(resolve_ref)
    [[ "$actual" == "$wanted" ]] || { printf 'Existing checkout is at another revision. Choose a new --source-dir; it will not be reset.\n' >&2; exit 1; }
  fi
else
  git clone --no-checkout -- https://github.com/playa77/cursus.git "$source_dir"
  resolved=$(resolve_ref)
  [[ "$resolved" =~ ^[0-9a-f]{40}$ ]] || { printf 'Cannot resolve requested source revision.\n' >&2; exit 1; }
  git -C "$source_dir" -c core.hooksPath=/dev/null checkout --detach "$resolved"
fi
[[ -f "$source_dir/deploy/install.py" ]] || { printf 'Selected source predates the unified installer. Select a release containing deploy/install.py.\n' >&2; exit 1; }
source_dir=$(cd -- "$source_dir" && pwd)
# Resolve caller-relative inputs before crossing the sudo/Python boundary.
[[ -z "$config" || "$config" == /* ]] || config="$PWD/$config"
[[ -z "$wheelhouse" || "$wheelhouse" == /* ]] || wheelhouse="$PWD/$wheelhouse"
args=(--host "$host" --source "$source_dir")
[[ -z "$config" ]] || args+=(--config "$config")
[[ -z "$wheelhouse" ]] || args+=(--wheelhouse "$wheelhouse")
((native_only)) && args+=(--native-only)
((stage_only)) && args+=(--stage-only)
((activate_existing)) && args+=(--activate-existing)
((noninteractive)) && args+=(--non-interactive)
# No caller environment/agent keys are propagated into the root installer.
exec "${privilege[@]}" env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 \
  python3 "$source_dir/deploy/install.py" "${args[@]}"
