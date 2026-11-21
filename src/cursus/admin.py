"""Operator-facing administration of the running deployment (ADR 0018).

Everything the website changes about configuration goes through this module, so there is one
place that decides what may change, how it is validated and how it reaches disk:

* every save builds a *candidate* `cursus.toml`, runs the real loader (`config.load`) on it and only
  then replaces the live file atomically, after keeping the previous one as a timestamped backup;
* roles and prompts are an immutable release: a change is validated, committed to the roles
  repository and pinned in one operation, and rolled back with a revert commit if pinning fails;
* secrets are write-only: nothing here ever returns, logs or echoes a token.

Settings take effect when the service restarts. `pending()` says whether the file on disk
differs from what is running. The module is synchronous and blocking; callers use a thread.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import copy
from hashlib import sha256
import grp
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
import tomllib
from urllib.parse import urlsplit

from cursus import config, tomlwrite
from cursus.contracts import Problem
from cursus.host import DEFAULT_PATH

HEADER = ('Managed by Cursus. Saving on the website rewrites this file after validating it and keeping the\n'
          'previous version in the state directory (backups/config). Hand edits are still honored: restart to apply.\n'
          'The keys are documented in deploy/cursus.example.toml; comments written here are not preserved.')
ROLES_HEADER = ('Cursus role release. Edit roles on the website (Settings, Roles) so the change is validated,\n'
                'committed and pinned; a hand edit must be committed and pinned (Settings, Roles) before restart.')
BACKUPS_KEPT = 50
RESTART_EXIT_STATUS = 75
TOOLS = ('read', 'list', 'search', 'write', 'edit', 'bash')


class FormProblem(Problem):
    """A rejected form: `errors` maps a form field name (or '') to a message for inline display."""

    def __init__(self, errors, code='invalid_fields'):
        self.errors = dict(errors)
        super().__init__(code, '; '.join(self.errors.values()))


# --- declarative settings: one definition drives validation and the rendered form -----------------

@dataclass(frozen=True)
class Field:
    path: tuple
    label: str
    kind: str                      # int | text | path | optpath | origin | list | dirs
    help: str = ''
    lo: int = 1
    hi: int | None = None

    @property
    def name(self):
        return '.'.join(self.path)

    def parse(self, raw):
        """Return the value to store, or None to remove an optional key. Raise ValueError(message)."""
        text = (raw or '').strip()
        if self.kind == 'int':
            if not re.fullmatch(r'\d{1,18}', text):
                raise ValueError('Enter a whole number.')
            number = int(text)
            if number < self.lo or (self.hi is not None and number > self.hi):
                raise ValueError(f'Must be between {self.lo} and {self.hi}.' if self.hi is not None
                                 else f'Must be at least {self.lo}.')
            return number
        if '\n' in text and self.kind != 'list':
            raise ValueError('Must be a single line.')
        if not text and self.kind in ('optpath', 'dirs', 'list'):
            return None
        if not text:
            raise ValueError('Required.')
        if len(text) > 4096:
            raise ValueError('Too long.')
        if self.kind in ('path', 'optpath'):
            if not text.startswith('/') or '\x00' in text:
                raise ValueError('Must be an absolute path.')
            return text
        if self.kind == 'dirs':
            dirs = text.split(':')
            if not all(d.startswith('/') for d in dirs):
                raise ValueError('Must be absolute directories separated by colons.')
            return ':'.join(dirs)
        if self.kind == 'origin':
            parts = urlsplit(text)
            if parts.scheme != 'https' or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username:
                raise ValueError('Must be an exact https origin, for example https://host.tailnet.ts.net')
            return text
        if self.kind == 'list':
            names = [n for n in re.split(r'[\s,]+', text) if n]
            if not all(re.fullmatch(r'[A-Z_][A-Z0-9_]*', n) for n in names):
                raise ValueError('Use uppercase variable names separated by commas or spaces.')
            return names
        return text


def _f(*path, **kw):
    return Field(tuple(path), **kw)


SECTIONS = {
    'access': ('Access', 'Who may open the website and where it is listening. The identity comes from the '
               'Tailscale Serve headers; a wrong login or origin locks you out of this site (restore the previous '
               'file from Settings, History or with cp, then restart).', [
        _f('service', 'external_origin', label='External origin', kind='origin',
           help='The exact https origin you open in the browser, for example https://host.tailnet.ts.net'),
        _f('service', 'operator_login', label='Operator login', kind='text',
           help='Your exact Tailscale login. Only this identity may use the website.'),
        _f('service', 'listen_port', label='Listen port', kind='int', lo=1, hi=65535,
           help='Loopback port the website listens on. Tailscale Serve must point here.'),
        _f('service', 'operator_group', label='Operator socket group', kind='text',
           help='Group allowed to use the operator socket (your own group on a single-user host).'),
    ]),
    'capacity': ('Capacity', 'Concurrent sessions per CLI. Sessions of one CLI share one login; the provider-side '
                 'effect of concurrency is unqualified.', [
        _f('capacity', 'worker', label='pi workers', kind='int', lo=1, hi=4, help='1 to 4 concurrent pi sessions.'),
        _f('capacity', 'claude', label='Claude Code sessions', kind='int', lo=1, hi=2, help='1 to 2.'),
        _f('capacity', 'codex', label='Codex CLI sessions', kind='int', lo=1, hi=2, help='1 to 2.'),
        _f('capacity', 'agy', label='Antigravity sessions', kind='int', lo=1, hi=2, help='1 to 2.'),
    ]),
    'resources': ('Resources and CLIs', 'New sessions wait while free disk or available memory is below the '
                  'reserves. A service starts with a minimal PATH, so say where your CLIs live.', [
        _f('execution', 'disk_reserve_mb', label='Disk reserve (MB)', kind='int', lo=1,
           help='New sessions wait while free disk is below this.'),
        _f('execution', 'host_reserve_mb', label='Memory reserve (MB)', kind='int', lo=1,
           help='New sessions wait while available memory is at or below this.'),
        _f('execution', 'path', label='Search path for the CLIs', kind='dirs',
           help='Absolute directories separated by colons. Empty uses the system default (' + DEFAULT_PATH + ').'),
        _f('execution', 'pass_env', label='Environment passed to CLIs', kind='list',
           help='Variable names copied from the service into the CLIs (for their login stores). Nothing else is inherited.'),
        _f('execution', 'clis', 'claude', label='Claude Code binary', kind='optpath', help='Optional absolute path; empty = search the path.'),
        _f('execution', 'clis', 'codex', label='Codex CLI binary', kind='optpath', help='Optional absolute path.'),
        _f('execution', 'clis', 'agy', label='Antigravity binary', kind='optpath', help='Optional absolute path.'),
        _f('execution', 'clis', 'pi', label='pi binary', kind='optpath', help='Optional absolute path.'),
    ]),
    'limits': ('Limits', 'Retry budgets, round caps and size bounds. The defaults are conservative.', [
        _f('limits', 'heartbeat_seconds', label='Heartbeat interval (s)', kind='int'),
        _f('limits', 'unreachable_after_missed_heartbeats', label='Missed heartbeats before unreachable', kind='int'),
        _f('limits', 'repair_retries', label='Repair retries', kind='int', help='Repair attempts after a failed check or review.'),
        _f('limits', 'interrupted_retries', label='Interrupted-step retries', kind='int', help='Then the phase parks.'),
        _f('limits', 'debate_rounds', label='Debate rounds', kind='int', hi=3, help='1 to 3.'),
        _f('limits', 'debug_turns', label='Debug turns', kind='int'),
        _f('limits', 'interview_rounds', label='Interview rounds', kind='int'),
        _f('limits', 'request_bytes', label='Request size (bytes)', kind='int'),
        _f('limits', 'spec_bytes', label='Specification size (bytes)', kind='int'),
        _f('limits', 'log_event_bytes', label='Log event size (bytes)', kind='int'),
        _f('limits', 'events_per_batch', label='Events per batch', kind='int'),
        _f('limits', 'artifact_bytes', label='Artifact size (bytes)', kind='int'),
        _f('limits', 'phase_artifact_bytes', label='Artifacts per phase (bytes)', kind='int'),
        _f('limits', 'spool_bytes', label='Runner spool (bytes)', kind='int'),
    ]),
    'publisher': ('Publisher', 'Where pull requests are published from. The token itself is write-only and is '
                  'set below; these are the files it is stored in.', [
        _f('publisher', 'git_binary', label='git binary', kind='path'),
        _f('publisher', 'git_credential_file', label='git credential file', kind='path',
           help='Private file in git credential-store format.'),
        _f('publisher', 'github_credential_file', label='GitHub token file', kind='path',
           help='Private file holding only the token.'),
    ]),
}

READ_ONLY = (
    ('service.user', 'Must equal the user running the service.'),
    ('service.listen_host', 'Always loopback; reach the site through Tailscale Serve.'),
    ('service.operator_socket', 'Where the terminal client finds the service.'),
    ('service.dsn_file', 'Database connection file (holds no secret for local socket access).'),
    ('service.state_root', 'Moving it would orphan existing state.'),
    ('service.artifact_root', 'Moving it would orphan existing artifacts.'),
    ('service.repository_root', 'Cache of repository clones.'),
    ('service.worktree_root', 'Per-attempt worktrees.'),
    ('service.review_root', 'Immutable review inputs.'),
    ('service.roles_file', 'Derived from the role release repository.'),
    ('service.prompts_root', 'Derived from the role release repository.'),
    ('runner.id', 'Identity of this runner in the database.'),
    ('capacity.verifier', 'Fixed at one lane by design (ADR 0016).'),
    ('capacity.repository', 'Fixed at one lane by design (ADR 0016).'),
)


def dig(data, dotted, default=None):
    for part in dotted.split('.'):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def changed_keys(old, new, prefix=''):
    """Dotted names whose value differs; lists (repositories) are compared as one unit."""
    names = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        dotted = f'{prefix}.{name}' if prefix else name
        if isinstance(a, dict) and isinstance(b, dict):
            names += changed_keys(a, b, dotted)
        elif a != b:
            names.append(dotted)
    return names


@dataclass(frozen=True)
class Item:
    key: str
    title: str
    state: str          # ok | todo | warn | info
    detail: str
    link: str | None = None


class Admin:
    def __init__(self, settings, config_path=None, supervised=None, environ=None):
        source = settings.get('_config') or {}
        path = config_path or source.get('path')
        if not path:
            raise Problem('invalid_config', 'The configuration file location is unknown.')
        self.path = Path(path)
        self.settings = settings
        self.loaded_sha = source.get('sha256') or sha256(self.path.read_bytes()).hexdigest()
        self.loaded_raw = copy.deepcopy(source.get('raw')) if source.get('raw') else tomllib.loads(self.path.read_text())
        self.lock = threading.Lock()
        environ = os.environ if environ is None else environ
        self.supervised = bool(environ.get('INVOCATION_ID')) if supervised is None else supervised
        self.restart_requested = False
        self.restart_hook = None   # set by the composition root: called to end the process cleanly
        service = settings['service']
        self.roles_root = Path(service['roles_file']).parent
        self.backup_root = Path(service['state_root']).parent / 'backups' / 'config'

    # --- reading --------------------------------------------------------------------------------

    def read_raw(self):
        return tomllib.loads(self.path.read_text(encoding='utf-8'))

    def current_sha(self):
        return sha256(self.path.read_bytes()).hexdigest()

    def pending(self):
        """Dotted names of settings that differ between the file on disk and the running process."""
        if self.current_sha() == self.loaded_sha:
            return []
        try:
            return changed_keys(self.loaded_raw, self.read_raw()) or ['(formatting only)']
        except (OSError, ValueError):
            return ['(file unreadable)']

    def values(self, section):
        """Current form values for a section, from the file on disk (what a save would build on)."""
        data = self.read_raw()
        out = {}
        for f in SECTIONS[section][2]:
            value = dig(data, f.name)
            out[f.name] = ', '.join(value) if isinstance(value, list) else ('' if value is None else str(value))
        return out

    def read_only(self):
        data = self.read_raw()
        return [(name, dig(data, name), why) for name, why in READ_ONLY]

    # --- writing configuration ------------------------------------------------------------------

    def save_section(self, section, form, actor):
        """Apply one settings form. Returns the dotted names that changed (empty: nothing written)."""
        if section not in SECTIONS:
            raise Problem('not_found', 'Unknown settings section.')
        errors, values = {}, {}
        for f in SECTIONS[section][2]:
            try:
                values[f] = f.parse(form.get(f.name, ''))
            except ValueError as exc:
                errors[f.name] = f'{f.label}: {exc}'
        if section == 'access' and 'service.operator_group' not in errors:
            try:
                grp.getgrnam(values[next(f for f in values if f.name == 'service.operator_group')])
            except KeyError:
                errors['service.operator_group'] = 'Operator socket group: no such group on this host.'
        if errors:
            raise FormProblem(errors)
        with self.lock:
            data = self.read_raw()
            changed = []
            for f, value in values.items():
                table = data
                for part in f.path[:-1]:
                    table = table.setdefault(part, {})
                old = table.get(f.path[-1])
                if value is None:
                    table.pop(f.path[-1], None)
                else:
                    table[f.path[-1]] = value
                if old != value:
                    changed.append(f.name)
            if isinstance(data.get('execution', {}).get('clis'), dict) and not data['execution']['clis']:
                del data['execution']['clis']
            if changed:
                self.commit_config(data)
            return changed

    def commit_config(self, data, text=None):
        """Validate a candidate with the real loader, back up the live file, replace it atomically."""
        text = text if text is not None else tomlwrite.dumps(data, HEADER)
        candidate = self.path.with_name('.' + self.path.name + '.candidate')
        candidate.unlink(missing_ok=True)
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                config.load('serve', str(candidate))
            except Problem as exc:
                raise FormProblem({'': f'Rejected, nothing was saved: {exc.message}'}, 'invalid_config') from None
            self.backup()
            os.replace(candidate, self.path)
        finally:
            candidate.unlink(missing_ok=True)

    def backup(self):
        self.backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = self.backup_root / f'cursus-{stamp}.toml'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(self.path.read_bytes())
        for old in sorted(self.backup_root.glob('cursus-*.toml'))[:-BACKUPS_KEPT]:
            old.unlink(missing_ok=True)

    def history(self):
        if not self.backup_root.is_dir():
            return []
        rows = []
        for item in sorted(self.backup_root.glob('cursus-*.toml'), reverse=True):
            info = item.stat()
            rows.append(dict(name=item.name, size=info.st_size,
                             time=datetime.fromtimestamp(info.st_mtime, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')))
        return rows

    def restore(self, name):
        if not re.fullmatch(r'cursus-\d{8}T\d{12}Z\.toml', name or ''):
            raise Problem('invalid_fields', 'Unknown backup name.')
        source = self.backup_root / name
        if not source.is_file():
            raise Problem('not_found', 'That backup no longer exists.')
        with self.lock:
            self.commit_config(None, source.read_text(encoding='utf-8'))

    # --- repositories ---------------------------------------------------------------------------

    def repositories(self):
        return self.read_raw().get('repositories', [])

    def repository(self, owner, name):
        for item in self.repositories():
            if (item['owner'], item['name']) == (owner, name):
                return item
        return None

    def save_repository(self, form, existing=None):
        """Create (existing=None) or update one enrollment from a form. Returns (owner, name)."""
        errors = {}
        owner = (existing or {}).get('owner') or form.get('owner', '').strip()
        name = (existing or {}).get('name') or form.get('name', '').strip()
        for label, field, value in (('Owner', 'owner', owner), ('Repository', 'name', name)):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.', '..'):
                errors[field] = f'{label}: letters, digits, dot, dash and underscore only.'
        fmt = form.get('object_format', 'sha1')
        if fmt not in ('sha1', 'sha256'):
            errors['object_format'] = 'Object format: sha1 or sha256.'
        refs = [r.strip() for r in form.get('allowed_target_refs', '').splitlines() if r.strip()]
        if not refs:
            errors['allowed_target_refs'] = 'Target refs: at least one (for example refs/heads/main).'
        elif not all(re.fullmatch(r'refs/heads/[A-Za-z0-9._/-]+', r) for r in refs):
            errors['allowed_target_refs'] = 'Target refs: each must look like refs/heads/NAME.'
        checks = []
        for index in range(int(form.get('check_rows', '0') or 0)):
            prefix = f'check.{index}.'
            ident = form.get(prefix + 'id', '').strip()
            argv = [a.strip('\r') for a in form.get(prefix + 'argv', '').split('\n') if a.strip('\r').strip()]
            if not ident and not argv:
                continue
            where = f'Check {index + 1}'
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', ident):
                errors[prefix + 'id'] = f'{where}: an id of letters, digits, dot, dash or underscore.'
            if not argv or not argv[0].startswith('/'):
                errors[prefix + 'argv'] = f'{where}: one argument per line; the first line must be an absolute path to the program.'
            cwd = form.get(prefix + 'cwd', '.').strip() or '.'
            if cwd != '.' and (cwd.startswith('/') or '..' in cwd.split('/')):
                errors[prefix + 'cwd'] = f'{where}: a relative directory inside the repository, or ".".'
            timeout = form.get(prefix + 'timeout_seconds', '300').strip()
            if not re.fullmatch(r'\d{1,6}', timeout) or int(timeout) < 1:
                errors[prefix + 'timeout_seconds'] = f'{where}: timeout in whole seconds.'
            checks.append(dict(id=ident, argv=argv, cwd=cwd, timeout_seconds=int(timeout) if timeout.isdigit() else 0))
        ids = [c['id'] for c in checks]
        if len(set(ids)) != len(ids):
            errors['checks'] = 'Check ids must be unique.'
        if not checks:
            errors['checks'] = 'At least one check is required: it is the evidence gate for every candidate.'
        phase_ids = [p for p in re.split(r'[\s,]+', form.get('phase_check_ids', '')) if p]
        if not phase_ids:
            errors['phase_check_ids'] = 'Phase checks: name at least one check id.'
        elif set(phase_ids) - set(ids):
            errors['phase_check_ids'] = 'Phase checks: every id must be one of the checks above.'
        if errors:
            raise FormProblem(errors)
        entry = dict(owner=owner, name=name, object_format=fmt, allowed_target_refs=refs,
                     phase_check_ids=phase_ids, checks=checks)
        with self.lock:
            data = self.read_raw()
            repos = data.setdefault('repositories', [])
            slot = next((i for i, r in enumerate(repos) if (r['owner'], r['name']) == (owner, name)), None)
            if existing is None and slot is not None:
                raise FormProblem({'name': 'That repository is already enrolled.'})
            if existing is not None and slot is None:
                raise Problem('not_found', 'Repository is not enrolled.')
            if slot is None:
                repos.append(entry)
            else:
                repos[slot] = entry
            self.commit_config(data)
        return owner, name

    def remove_repository(self, owner, name):
        with self.lock:
            data = self.read_raw()
            kept = [r for r in data.get('repositories', []) if (r['owner'], r['name']) != (owner, name)]
            if len(kept) == len(data.get('repositories', [])):
                raise Problem('not_found', 'Repository is not enrolled.')
            data['repositories'] = kept
            if not kept:
                del data['repositories']
            self.commit_config(data)

    # --- publisher credential (write-only) ------------------------------------------------------

    def credential_status(self):
        """Presence and permissions of the two credential files; never any content."""
        out = {}
        for key in ('github_credential_file', 'git_credential_file'):
            path = Path(dig(self.read_raw(), 'publisher.' + key, ''))
            try:
                info = path.stat()
                private = stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077
                out[key] = dict(path=str(path), present=info.st_size > 0, private=private,
                                time=datetime.fromtimestamp(info.st_mtime, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
            except OSError:
                out[key] = dict(path=str(path), present=False, private=False, time=None)
        return out

    def set_token(self, token):
        """Write the GitHub token to both private credential files. The value never leaves this call."""
        token = (token or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.~-]{8,255}', token):
            raise FormProblem({'token': 'Token: 8 to 255 characters from A-Z a-z 0-9 _ . ~ - (a GitHub token has no other characters).'})
        publisher = self.read_raw()['publisher']
        for key, content in (('github_credential_file', token + '\n'),
                             ('git_credential_file', f'https://x-access-token:{token}@github.com\n')):
            target = Path(publisher[key])
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=target.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)

    # --- roles and prompts (an immutable, committed, pinned release) ----------------------------

    def git(self, *args, check=True):
        git = self.read_raw()['publisher']['git_binary']
        base = [git, '-c', f'safe.directory={self.roles_root}', '-c', 'commit.gpgsign=false',
                '-c', 'core.hooksPath=/dev/null', '-C', str(self.roles_root)]
        return subprocess.run([*base, *args], capture_output=True, text=True, check=check)

    def release_state(self):
        head = self.git('rev-parse', 'HEAD', check=False).stdout.strip()
        dirty = bool(self.git('status', '--porcelain', check=False).stdout.strip())
        pin = dig(self.read_raw(), 'service.role_release_commit', '')
        return dict(pin=pin, head=head, dirty=dirty, differs=bool(head) and head != pin)

    def roles_registry(self):
        return tomllib.loads((self.roles_root / 'roles.toml').read_text(encoding='utf-8'))

    def prompt_names(self):
        return sorted(p.name for p in (self.roles_root / 'prompts').glob('*.md'))

    def prompt_text(self, name):
        if name not in self.prompt_names():
            raise Problem('not_found', 'Unknown prompt.')
        return (self.roles_root / 'prompts' / name).read_text(encoding='utf-8')

    def roles_view(self):
        """Roles as the file on disk defines them, with qualification and the role-set rules."""
        registry = self.roles_registry()
        view = {}
        for name, role in registry['roles'].items():
            holes = [k for k in ('model', 'reasoning', 'provider') if 'REPLACE_' in str(role.get(k, ''))]
            view[name] = dict(role, name=name, holes=holes, qualified=not holes)
        return view

    def _validate_roles(self, registry, prompts=None):
        """Run the startup validation on a candidate registry using candidate prompt texts."""
        with tempfile.TemporaryDirectory(prefix='cursus-roles-') as directory:
            root = Path(directory)
            for name in self.prompt_names():
                (root / name).write_text((prompts or {}).get(name, self.prompt_text(name)), encoding='utf-8')
            for name, text in (prompts or {}).items():
                (root / name).write_text(text, encoding='utf-8')
            try:
                config.parse_registry(copy.deepcopy(registry), str(root))
            except Problem as exc:
                raise FormProblem({'': f'Rejected, nothing was saved: {exc.message}'}, 'invalid_config') from None
            except (OSError, KeyError, TypeError) as exc:
                raise FormProblem({'': f'Rejected, nothing was saved: invalid role definition ({type(exc).__name__}).'}) from None

    def save_role(self, name, form, actor):
        with self.lock:
            registry = self.roles_registry()
            if name not in registry['roles']:
                raise Problem('not_found', 'Unknown role.')
            old = registry['roles'][name]
            errors = {}
            tier, cli = form.get('tier', ''), form.get('cli', '')
            if tier not in ('production', 'organization'):
                errors['tier'] = 'Tier: production or organization.'
            if cli not in ('pi', 'claude', 'codex', 'agy'):
                errors['cli'] = 'CLI: one of pi, claude, codex, agy.'
            tools = [t for t in TOOLS if form.get('tool.' + t) == 'on']
            if not tools:
                errors['tools'] = 'Tools: choose at least one.'
            timeout = form.get('timeout_seconds', '').strip()
            if not re.fullmatch(r'\d{1,6}', timeout) or int(timeout) < 1:
                errors['timeout_seconds'] = 'Timeout: whole seconds.'
            values = {}
            for key, label in (('model', 'Model'), ('reasoning', 'Reasoning'), ('provider', 'Provider')):
                values[key] = form.get(key, '').strip()
                if values[key] and not (re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]*', values[key]) or 'REPLACE_' in values[key]):
                    errors[key] = f'{label}: a plain identifier (letters, digits and . _ : / @ + -, no spaces, not starting with -).'
            if not values['model']:
                errors['model'] = 'Model: required.'
            if not values['reasoning']:
                errors['reasoning'] = 'Reasoning: required (the CLI\'s effort or thinking level).'
            prompt = form.get('prompt', '')
            if prompt not in self.prompt_names():
                errors['prompt'] = 'Prompt: choose an existing prompt file.'
            if errors:
                raise FormProblem(errors)
            role = dict(old, tier=tier, cli=cli, tools=tools, timeout_seconds=int(timeout), prompt=prompt,
                        model=values['model'], reasoning=values['reasoning'])
            if values['provider']:
                role['provider'] = values['provider']
            else:
                role.pop('provider', None)
            registry['roles'][name] = role
            self._validate_roles(registry)
            if role == old:
                return None
            return self._release({'roles.toml': tomlwrite.dumps(registry, ROLES_HEADER)}, f'Role {name}', actor)

    def save_prompt(self, name, text, actor):
        with self.lock:
            if name not in self.prompt_names():
                raise Problem('not_found', 'Unknown prompt.')
            text = text.replace('\r\n', '\n')
            if not text.strip() or len(text.encode('utf-8')) > 262144:
                raise FormProblem({'text': 'Prompt: required, at most 256 KiB.'})
            if text == self.prompt_text(name):
                return None
            self._validate_roles(self.roles_registry(), {name: text})
            return self._release({'prompts/' + name: text}, f'Prompt {name}', actor)

    def pin_current(self, actor):
        """Validate the role files as they are on disk, commit them if dirty, pin HEAD."""
        with self.lock:
            self._validate_roles(self.roles_registry())
            if self.release_state()['dirty']:
                return self._release({}, 'Pin current role files', actor)
            head = self.release_state()['head']
            data = self.read_raw()
            if dig(data, 'service.role_release_commit') == head:
                return None
            data['service']['role_release_commit'] = head
            self.commit_config(data)
            return head

    def _release(self, files, subject, actor):
        """Write files, commit them as a visible role release, pin the commit; revert on failure."""
        for relative, text in files.items():
            target = self.roles_root / relative
            fd, temporary = tempfile.mkstemp(prefix='.release-', dir=target.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(text)
            os.chmod(temporary, 0o644)
            os.replace(temporary, target)
        who = actor if actor else 'operator'
        identity = ['-c', 'user.name=Cursus website', '-c', f'user.email={who if "@" in who else "cursus@localhost"}']
        self.git('add', 'roles.toml', 'prompts')
        self.git(*identity, 'commit', '-q', '-m', f'{subject}: changed on the website by {who}')
        commit = self.git('rev-parse', 'HEAD').stdout.strip()
        try:
            data = self.read_raw()
            data['service']['role_release_commit'] = commit
            self.commit_config(data)
        except Exception:
            # Keep the tree equal to the still-pinned release without discarding history.
            self.git(*identity, 'revert', '--no-edit', commit, check=False)
            raise
        return commit

    # --- running state --------------------------------------------------------------------------

    def required_clis(self):
        return sorted({r['cli'] for r in self.roles_view().values()})

    def execution_settings(self):
        return dict(self.read_raw().get('execution', {}))

    def checklist(self):
        from cursus.recipes import discover
        items = []
        try:
            view = self.roles_view()
            holes = sorted(n for n, r in view.items() if not r['qualified'])
            items.append(Item('roles', 'Roles qualified', 'todo' if holes else 'ok',
                              ('Choose a model, reasoning level and provider for: ' + ', '.join(holes) + '.') if holes
                              else 'Every role has a model and reasoning level.', '/settings/roles'))
            needed = sorted({r['cli'] for r in view.values()})
            found = discover(self.execution_settings())
            missing = [c for c in needed if c not in found]
            items.append(Item('clis', 'CLIs installed', 'todo' if missing else 'ok',
                              ('Not found: ' + ', '.join(missing) + '. Install them, or point the roles at CLIs you have, '
                               'or set their location under Resources.') if missing
                              else 'Found: ' + ', '.join(f'{c} ({found[c]})' for c in needed) + '.', '/settings/system'))
            items.append(Item('signin', 'CLIs signed in', 'info',
                              'Cursus cannot tell. Sign in to ' + ', '.join(needed) + ' as the user running Cursus; '
                              'a signed-out CLI fails on its first use.', None))
        except (Problem, OSError, ValueError, KeyError) as exc:
            items.append(Item('roles', 'Roles', 'todo', f'The role files could not be read: {getattr(exc, "message", exc)}', '/settings/roles'))
        status = self.credential_status()
        ready = all(s['present'] and s['private'] for s in status.values())
        items.append(Item('token', 'GitHub token', 'ok' if ready else 'todo',
                          'Stored privately.' if ready else 'Needed to publish pull requests. Not needed to try the website.',
                          '/settings/publisher'))
        count = len(self.repositories())
        items.append(Item('repos', 'Repository enrolled', 'ok' if count else 'todo',
                          f'{count} enrolled.' if count else 'Enroll a repository and its check commands to create runs.',
                          '/settings/repositories'))
        pending = self.pending()
        if pending:
            items.append(Item('restart', 'Restart to apply', 'warn',
                              'Saved but not running yet: ' + ', '.join(pending[:8]) + ('…' if len(pending) > 8 else ''),
                              '/settings/system'))
        return items

    async def preflight(self):
        """Version/help queries only (no inference, no sign-in check) for each CLI the roles use."""
        import asyncio
        from cursus.recipes import preflight, resolve
        execution = self.execution_settings()
        async def one(cli):
            binary = resolve(cli, execution)
            if binary is None:
                return dict(cli=cli, binary=None, ok=False, version=None, missing=[],
                            error='Not found. Install it, then list its directory under Resources.')
            return await preflight(cli, binary, execution)
        return list(await asyncio.gather(*(one(c) for c in self.required_clis())))

    def request_restart(self):
        if not self.supervised:
            raise Problem('unavailable', 'Cursus is not running under systemd, so it cannot restart itself. '
                          'Stop it and start it again.')
        self.restart_requested = True
        if self.restart_hook:
            self.restart_hook()
