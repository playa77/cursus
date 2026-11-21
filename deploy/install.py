#!/usr/bin/env python3
"""Per-user Cursus installer (ADR 0017, completed by ADR 0018).

Runs as the user whose already-installed, already-signed-in CLIs Cursus will use, and finishes the
job: packages, private directories, the role release (committed and pinned), a complete
configuration, the PostgreSQL role and database, the user service unit, lingering, and starting the
service, then verifies that it answers. It derives every value the machine can answer and leaves only
what cannot be known (signing in to the CLIs, the model of each role, the GitHub token, repositories)
to the website. It never overwrites an operator's values, never signs in to a CLI and never touches
a credential. `sudo` is used for exactly one thing: creating the PostgreSQL role and database.
"""
import argparse
from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
STATE_DIRECTORIES = ('state', 'artifacts', 'repositories', 'worktrees', 'reviews', 'backups')
SOURCE_FILES = ('requirements.lock', 'pyproject.toml', 'roles.toml', 'deploy/cursus.example.toml', 'deploy/cursus.service',
                'src/cursus/tomlwrite.py')
DEFAULT_DSN = 'postgresql:///cursus'
DEFAULT_PATH = ('/usr/local/sbin', '/usr/local/bin', '/usr/sbin', '/usr/bin', '/sbin', '/bin')
PASS_ENV = ['XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS']
CAPACITY = {'worker': 2, 'claude': 1, 'codex': 1, 'agy': 1}
LISTEN_PORT = 8787
READY_SECONDS = 60


class InstallError(Exception):
    pass


class Step(Exception):
    """One way of doing something failed; the caller may try another."""


def tail(text, lines=6):
    return '\n'.join(' | ' + line for line in (text or '').strip().splitlines()[-lines:])


class Installer:
    def __init__(self, home=None, source=None, run=None, which=None, out=print,
                 user=None, group=None, runtime_dir=None, wheelhouse=None, environ=None,
                 origin=None, operator_login=None, start=True, interactive=None, sleep=time.sleep,
                 meminfo='/proc/meminfo'):
        self.home = Path(home) if home else Path.home()
        self.source = Path(source) if source else ROOT
        self.run, self.which, self.out, self.sleep = run or subprocess.run, which or shutil.which, out, sleep
        self.environ = os.environ if environ is None else environ
        self.user = user or pwd.getpwuid(os.getuid()).pw_name
        self.group = group or grp.getgrgid(os.getgid()).gr_name
        self.runtime_dir = runtime_dir or self.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
        self.wheelhouse = Path(wheelhouse) if wheelhouse else None
        self.origin, self.operator_login = origin, operator_login
        self.start, self.interactive, self.meminfo = start, sys.stdin.isatty() if interactive is None else interactive, meminfo
        self.config = self.home / '.config' / 'cursus'
        self.state = self.home / '.local' / 'state' / 'cursus'
        self.venv = self.home / '.local' / 'share' / 'cursus' / 'venv'
        self.unit = self.home / '.config' / 'systemd' / 'user' / 'cursus.service'
        self.pin = None        # role release commit, once the release repository exists
        self.serve_notice = None

    # --- helpers --------------------------------------------------------------------------------

    def capture(self, argv, **kw):
        kw.setdefault('capture_output', True)
        kw.setdefault('text', True)
        kw.setdefault('check', False)
        return self.run([str(a) for a in argv], **kw)

    def tomlwrite(self):
        sys.path.insert(0, str(self.source / 'src'))
        try:
            from cursus import tomlwrite
        finally:
            sys.path.pop(0)
        return tomlwrite

    # --- checks (no side effects) ---------------------------------------------------------------

    def check(self):
        if sys.version_info < (3, 12):
            raise InstallError('Python 3.12 or newer is required.')
        if not self.which('git'):
            raise InstallError('git is required (for the role release and the checkout).')
        missing = [name for name in SOURCE_FILES if not (self.source / name).is_file()]
        if missing or not (self.source / 'prompts').is_dir():
            raise InstallError('This does not look like a Cursus checkout; missing: ' + ', '.join(missing or ['prompts/']))
        if not self.which('psql'):
            raise InstallError(
                'The PostgreSQL client (psql) was not found. Cursus stores its state in PostgreSQL 16 or newer, and the '
                'installer creates the role and database for you, but it does not install PostgreSQL itself. Install it '
                '(on Debian or Ubuntu: sudo apt install postgresql), make sure the server is running, and run the '
                'installer again.')
        if self.start and not self.which('systemctl'):
            raise InstallError(
                'systemctl was not found, so the installer cannot start Cursus as a user service. Run the installer '
                'with --no-start to install without starting, then run "cursus serve --config" yourself.')

    def recipes(self):
        sys.path.insert(0, str(self.source / 'src'))
        try:
            from cursus import recipes
        finally:
            sys.path.pop(0)
        return recipes

    def cli_report(self):
        """Which CLIs the default roles use are findable on this user's PATH (informational)."""
        recipes = self.recipes()
        found = recipes.discover({'path': ':'.join(self.search_path()) or '/usr/bin'})
        return found, sorted(set(recipes.EXECUTABLES) - set(found))

    def search_path(self):
        """The installing user's own absolute, existing PATH entries, then the system defaults."""
        seen, result = set(), []
        for directory in [*self.environ.get('PATH', '').split(':'), *DEFAULT_PATH]:
            if directory.startswith('/') and directory not in seen and Path(directory).is_dir():
                seen.add(directory)
                result.append(directory)
        return result

    def access(self):
        """The website's origin and the operator's login: flags, else the Tailscale node. Stops with prose."""
        if self.origin and self.operator_login:
            return self.origin, self.operator_login
        ts = self.which('tailscale')
        reason = None
        if not ts:
            reason = 'the tailscale command was not found'
        else:
            result = self.capture([ts, 'status', '--json'])
            if result.returncode:
                reason = 'tailscale did not answer (' + (result.stderr or result.stdout or 'no output').strip().splitlines()[-1][:160] + ')'
            else:
                try:
                    status = json.loads(result.stdout)
                    me = status['Self']
                    login = status['User'][str(me['UserID'])]['LoginName']
                    name = (me.get('DNSName') or '').rstrip('.')
                    if status.get('BackendState') != 'Running':
                        reason = f'Tailscale is not connected (state: {status.get("BackendState")})'
                    elif not name:
                        reason = 'this node has no MagicDNS name, so there is no HTTPS address to publish'
                    elif not login:
                        reason = 'this node belongs to no user (it may be a tagged node)'
                    else:
                        self.origin = self.origin or 'https://' + name
                        self.operator_login = self.operator_login or login
                except (ValueError, KeyError, TypeError):
                    reason = 'tailscale status could not be read'
        if reason:
            raise InstallError(
                'Cursus is reached through your Tailscale network: the website listens on this machine only, and '
                'Tailscale Serve gives it an HTTPS address and tells it who you are. Only that identity may use it.\n'
                f'The installer could not determine it because {reason}.\n'
                'Nothing was changed. To continue:\n'
                '  - Install Tailscale, sign in, and enable MagicDNS and HTTPS certificates for your tailnet '
                '(https://tailscale.com/kb/1153/enabling-https), then run the installer again; or\n'
                '  - If you reach this machine some other way, pass both values yourself:\n'
                '      ./install.sh --origin https://HOST.TAILNET.ts.net --operator-login you@example.com\n'
                'The installer does not install, configure or sign in to Tailscale.')
        self.serve_notice = self.serve_status()
        return self.origin, self.operator_login

    def serve_status(self):
        ts = self.which('tailscale')
        if not ts:
            return None
        result = self.capture([ts, 'serve', 'status', '--json'])
        if result.returncode == 0 and re.search(rf'(127\.0\.0\.1|localhost):{LISTEN_PORT}\b', result.stdout or ''):
            return None
        return f'tailscale serve --bg {LISTEN_PORT}'

    def derived(self):
        """Everything the machine can answer, as dotted names. Policy lives in the GUI, with these defaults."""
        meminfo = 0
        try:
            meminfo = next(int(line.split()[1]) for line in Path(self.meminfo).read_text().splitlines()
                           if line.startswith('MemTotal:')) // 1024
        except (OSError, StopIteration, ValueError):
            pass
        probe = self.state if self.state.exists() else self.home
        try:
            disk = shutil.disk_usage(probe).total // (1024 * 1024)
        except OSError:
            disk = 0
        origin, login = self.origin, self.operator_login
        values = {
            'service.user': self.user, 'service.operator_group': self.group,
            'service.operator_socket': f'{self.runtime_dir}/cursus/operator.sock',
            'service.external_origin': origin, 'service.operator_login': login,
            'service.role_release_commit': self.pin, 'runner.id': str(uuid4()),
            'execution.disk_reserve_mb': max(512, min(5120, disk // 10)) if disk else 5120,
            'execution.host_reserve_mb': max(512, min(4096, meminfo // 10)) if meminfo else 1024,
        }
        values.update({f'capacity.{name}': number for name, number in CAPACITY.items()})
        return {key: value for key, value in values.items() if value is not None}

    def tokens(self):
        return {'REPLACE_SIGNED_IN_USER': self.user, 'REPLACE_GROUP': self.group, 'REPLACE_RUNTIME_DIR': self.runtime_dir,
                'REPLACE_HOME': str(self.home), 'REPLACE_SOURCE': str(self.config / 'roles')}

    def plan(self):
        def state(path):
            return 'kept, already exists' if path.exists() else 'created'
        dsn = self.config / 'database-dsn'
        lines = [
            f'Private directories: {self.config}, {self.state} (mode 0700)',
            f'Python environment {self.venv}: ' + ('reused' if (self.venv / 'bin' / 'python').exists() else 'created')
            + '; hash-checked packages from requirements.lock' + (f' (offline from {self.wheelhouse})' if self.wheelhouse else '')
            + ' and this checkout refreshed',
            f'Role release {self.config / "roles"}: {state(self.config / "roles")}; committed and pinned',
            f'Configuration {self.config / "cursus.toml"}: ' + ('kept; unfilled placeholders are completed' if (self.config / 'cursus.toml').exists()
                                                           else 'created, complete (conservative capacity and reserves; change them on the website)'),
            f'Website: {self.origin} for {self.operator_login}',
            f'PostgreSQL: role "{self.user}" and database "cursus": ' + self.database_state(dsn)
            + ' (sudo is used only for this, and only if needed)',
            f'DSN file {dsn}: {state(dsn)}',
            f'User service unit {self.unit}: ' + ('kept; a differing new one is written beside it' if self.unit.exists() else 'created'),
        ]
        if self.start:
            lines.append(f'Lingering for {self.user}, then enable and start the service and wait until it answers')
        else:
            lines.append('The service is not started (--no-start)')
        return lines

    def database_state(self, dsn):
        psql = self.which('psql')
        target = dsn.read_text().strip() if dsn.exists() else DEFAULT_DSN
        if psql and self.capture([psql, '-X', '-q', '-tA', '-d', target, '-c', 'SELECT 1'], cwd='/').returncode == 0:
            return 'already reachable'
        return 'will be created'

    # --- changes --------------------------------------------------------------------------------

    def apply(self):
        self.check()
        if not (self.origin and self.operator_login):
            self.access()
        self.directories()
        self.environment()
        self.pin = self.roles()
        self.dsn()
        self.configuration()
        self.database()
        self.service_unit()
        if self.start:
            self.launch()

    def private_directory(self, path):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)

    def private_file(self, path, text):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)

    def directories(self):
        for path in (self.config, self.state, *(self.state / name for name in STATE_DIRECTORIES), self.venv.parent):
            self.private_directory(path)

    def environment(self):
        python = self.venv / 'bin' / 'python'
        if not python.exists():
            self.out(f'Creating the Python environment {self.venv} ...')
            self.run([sys.executable, '-m', 'venv', str(self.venv)], check=True)
        offline = ['--no-index', '--find-links', str(self.wheelhouse)] if self.wheelhouse else []
        self.out('Installing hash-checked dependencies and Cursus ...')
        self.run([str(python), '-m', 'pip', 'install', '--require-hashes', *offline, '-r', str(self.source / 'requirements.lock')], check=True)
        self.run([str(python), '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '--force-reinstall', *offline, str(self.source)], check=True)

    def git(self, *args, target=None):
        target = target or self.config / 'roles'
        base = [self.which('git'), '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                '-c', 'user.name=Cursus installer', '-c', 'user.email=cursus@localhost', '-C', str(target)]
        return self.run([*base, *args], capture_output=True, text=True, check=True)

    def roles(self):
        """Create the role release if absent; commit any uncommitted edits; return the commit to pin."""
        target = self.config / 'roles'
        if not target.exists():
            (target / 'prompts').mkdir(parents=True)
            shutil.copy2(self.source / 'roles.toml', target / 'roles.toml')
            for prompt in sorted((self.source / 'prompts').glob('*.md')):
                shutil.copy2(prompt, target / 'prompts' / prompt.name)
            self.git('init', '-q')
            self.git('add', '.')
            self.git('commit', '-q', '-m', 'Initial role release (unedited)')
            self.out(f'Created the role release {target}. Choose each role\'s model on the website (Settings, Roles).')
        elif self.git('status', '--porcelain').stdout.strip():
            self.git('add', 'roles.toml', 'prompts')
            self.git('commit', '-q', '-m', 'Installer: commit role edits found on disk so they can be pinned')
            self.out(f'Committed the uncommitted edits found in {target} so they can be pinned.')
        else:
            self.out(f'Kept the existing role release {target}.')
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def dsn(self):
        path = self.config / 'database-dsn'
        if path.exists():
            self.out(f'Kept the existing {path}.')
        else:
            # Peer authentication over the local socket as this user: the file holds no secret.
            self.private_file(path, DEFAULT_DSN + '\n')
            self.out(f'Wrote {path} (local PostgreSQL socket, this user, database "cursus").')

    def search_settings(self):
        found = self.search_path()
        for binary in self.recipes().discover({'path': ':'.join(found)}).values():
            directory = str(Path(binary).parent)
            if directory not in found:
                found.insert(0, directory)
        return ':'.join(found)

    def substitute(self, value, derived, fill_numbers):
        """Fill REPLACE_ tokens in a parsed document in place; return the dotted names still unfilled."""
        left = []
        tokens = self.tokens()

        def walk(item, path):
            if isinstance(item, dict):
                for key, sub in list(item.items()):
                    dotted = f'{path}.{key}' if path else key
                    if isinstance(sub, str) and 'REPLACE_' in sub:
                        text = sub
                        for token, replacement in tokens.items():
                            text = text.replace(token, str(replacement))
                        if 'REPLACE_' in text and dotted in derived and (fill_numbers or isinstance(derived[dotted], str)):
                            text = derived[dotted]
                        if isinstance(text, str) and 'REPLACE_' in text:
                            left.append(dotted)
                        item[key] = text
                    elif isinstance(sub, (dict, list)):
                        walk(sub, dotted)
            elif isinstance(item, list):
                for index, sub in enumerate(item):
                    if isinstance(sub, (dict, list)):
                        walk(sub, f'{path}[{index}]')
        walk(value, '')
        return left

    def configuration(self):
        path = self.config / 'cursus.toml'
        writer = self.tomlwrite()
        derived = self.derived()
        header = ('Managed by Cursus. Settings made on the website rewrite this file after validating it; hand edits\n'
                  'are still honored (restart to apply). The keys are documented in deploy/cursus.example.toml.')
        if not path.exists():
            data = tomllib.loads((self.source / 'deploy' / 'cursus.example.toml').read_text(encoding='utf-8'))
            left = self.substitute(data, derived, fill_numbers=True)
            data['service']['listen_port'] = LISTEN_PORT
            data['execution'].update(path=self.search_settings(), pass_env=PASS_ENV)
            if left:
                raise InstallError('Internal error: no value was derived for ' + ', '.join(left))
            self.private_file(path, writer.dumps(data, header))
            self.out(f'Wrote {path}: every value derived from this machine; adjust capacity and reserves on the website.')
            return
        data = tomllib.loads(path.read_text(encoding='utf-8'))
        left = self.substitute(data, derived, fill_numbers=True)
        before = tomllib.loads(path.read_text(encoding='utf-8'))
        if data == before:
            self.out(f'Kept the existing {path}.')
            return
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = path.with_name(f'cursus.toml.bak-{stamp}')
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        text = writer.dumps(data, header)
        temporary = path.with_name('.cursus.toml.installer')
        temporary.unlink(missing_ok=True)
        self.private_file(temporary, text)
        os.replace(temporary, path)
        self.out(f'Completed the unfilled values in {path} (previous copy: {backup}).')
        if left:
            self.out('Still to fill by hand or on the website: ' + ', '.join(left))

    def database(self):
        dsn = (self.config / 'database-dsn').read_text().strip()
        psql = self.which('psql')
        reachable = lambda: self.capture([psql, '-X', '-q', '-tA', '-d', dsn, '-c', 'SELECT 1'], cwd='/').returncode == 0
        if reachable():
            self.out(f'PostgreSQL: {dsn} already works.')
            return
        if dsn != DEFAULT_DSN:
            raise InstallError(
                f'The database named in {self.config / "database-dsn"} cannot be reached, and it is not the default '
                f'({DEFAULT_DSN}) that the installer knows how to create. Fix that file or the server, then run the '
                'installer again.')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', self.user):
            raise InstallError(f'The user name "{self.user}" is not one the installer will place in SQL. '
                               f'Create the role and database by hand: createuser, then createdb -O USER cursus.')
        self.out(f'Creating the PostgreSQL role "{self.user}" and database "cursus" ...')
        attempts = [(f'as {self.user}', [])]
        if self.which('sudo'):
            attempts.append(('with sudo -n -u postgres', ['sudo', '-n', '-u', 'postgres']))
            if self.interactive:
                attempts.append(('with sudo -u postgres (you may be asked for your password)', ['sudo', '-u', 'postgres']))
        failures = []
        for label, prefix in attempts:
            try:
                self.provision(prefix, psql)
                break
            except Step as exc:
                failures.append(f'  - {label}: {exc}')
        else:
            raise InstallError(
                'The PostgreSQL role and database could not be created.\n' + '\n'.join(failures) + '\n'
                'Is the server running (pg_isready) and may your user use sudo to act as the postgres user? You can '
                f'create them yourself and run the installer again:\n'
                f'  sudo -u postgres createuser {shlex.quote(self.user)}\n  sudo -u postgres createdb -O {shlex.quote(self.user)} cursus')
        if not reachable():
            raise InstallError(
                f'The role and database exist, but connecting as {self.user} through the local socket still fails. '
                'PostgreSQL probably does not use peer authentication for local connections (see pg_hba.conf), which '
                'is what the default connection file assumes. Put a connection string that works in '
                f'{self.config / "database-dsn"} (it may contain a password: keep the file private) and run the installer again.')
        self.out('PostgreSQL role and database are ready.')

    def provision(self, prefix, psql):
        def sql(statement):
            result = self.capture([*prefix, psql, '-X', '-q', '-tA', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres', '-c', statement], cwd='/')
            if result.returncode:
                raise Step(((result.stderr or result.stdout or '').strip().splitlines() or ['failed'])[-1][:200])
            return (result.stdout or '').strip()
        if not sql(f"SELECT 1 FROM pg_roles WHERE rolname = '{self.user}'"):
            sql(f'CREATE ROLE "{self.user}" LOGIN')
        if not sql("SELECT 1 FROM pg_database WHERE datname = 'cursus'"):
            sql(f'CREATE DATABASE cursus OWNER "{self.user}"')

    def service_unit(self):
        wanted = (self.source / 'deploy' / 'cursus.service').read_text(encoding='utf-8')
        self.unit.parent.mkdir(parents=True, exist_ok=True)
        if not self.unit.exists():
            self.unit.write_text(wanted, encoding='utf-8')
            self.out(f'Installed {self.unit}.')
        elif self.unit.read_text(encoding='utf-8') != wanted:
            beside = self.unit.with_name(self.unit.name + '.new')
            beside.write_text(wanted, encoding='utf-8')
            self.out(f'Kept your existing {self.unit}; the shipped unit is at {beside} for you to compare.')
        systemctl = self.which('systemctl')
        if systemctl:
            result = self.capture([systemctl, '--user', 'daemon-reload'])
            if result.returncode and not self.start:
                self.out('systemctl --user daemon-reload failed (no user session here?); run it yourself later.')

    def systemd_failure(self, result, action):
        return InstallError(
            f'Could not {action} through systemd:\n{tail(result.stderr or result.stdout)}\n'
            'Cursus runs as a systemd user service, which needs your user session. If you installed over a plain su or '
            'sudo shell, log in normally (or use ssh/a console) and run the installer again. Everything else is '
            'already in place, so a rerun finishes quickly. To run Cursus without systemd for now:\n'
            f'  {self.venv / "bin" / "cursus"} serve --config {self.config / "cursus.toml"}')

    def launch(self):
        systemctl = self.which('systemctl')
        result = self.capture([systemctl, '--user', 'daemon-reload'])
        if result.returncode:
            raise self.systemd_failure(result, 'reach your user service manager')
        loginctl = self.which('loginctl')
        if loginctl:
            result = self.capture([loginctl, 'enable-linger', self.user])
            if result.returncode:
                self.out(f'Could not enable lingering ({tail(result.stderr or result.stdout, 1).strip(" |")}). Cursus will stop when you '
                         f'log out. To keep it running: sudo loginctl enable-linger {shlex.quote(self.user)}')
        if self.capture([systemctl, '--user', 'is-active', '--quiet', 'cursus']).returncode == 0:
            self.out('Cursus is already running. It keeps running the version it started with; restart it from '
                     'Settings, System on the website (drain first) or with "systemctl --user restart cursus" to use this one.')
            return
        result = self.capture([systemctl, '--user', 'enable', '--now', 'cursus'])
        if result.returncode:
            raise self.systemd_failure(result, 'enable and start Cursus')
        self.out('Started Cursus; waiting for it to answer ...')
        binary = self.venv / 'bin' / 'cursus'
        socket = f'{self.runtime_dir}/cursus/operator.sock'
        waited = 0
        while waited <= READY_SECONDS:
            if self.capture([binary, 'status', '--deployment', '--socket', socket]).returncode == 0:
                self.out('Cursus is running.')
                return
            if self.capture([systemctl, '--user', 'is-active', 'cursus']).stdout.strip() == 'failed':
                break
            self.sleep(2)
            waited += 2
        journal = self.capture([self.which('journalctl') or 'journalctl', '--user', '-u', 'cursus', '-n', '30', '--no-pager'])
        raise InstallError('Cursus was started but did not become ready. Its log:\n' + tail(journal.stdout, 30) + '\n'
                           'Fix the cause above and run the installer again, or read: journalctl --user -u cursus -n 80')

    def summary(self):
        binary = self.venv / 'bin' / 'cursus'
        found, missing = self.cli_report()
        lines = ['', f'Cursus is installed{" and running" if self.start else ""}.', '',
                 f'  Open:  {self.origin}    (only {self.operator_login} may use it)']
        if self.serve_notice:
            lines += ['', f'  Tailscale is not publishing the website yet. Publish it with:  {self.serve_notice}',
                      '  (the installer does not configure Tailscale)']
        lines += ['', 'Left for you, because Cursus cannot know them:',
                  f'  1. Sign in to each CLI your roles use as {self.user}. Cursus cannot tell whether a CLI is signed in.',
                  '  2. On the website, Settings, Roles: choose each role\'s model and reasoning level.',
                  '  3. When you want pull requests: Settings, Publisher (GitHub token) and Settings, Repositories.',
                  '', 'CLIs found: ' + (', '.join(f'{c} ({p})' for c, p in sorted(found.items())) or 'none')]
        if missing:
            lines.append('Not found: ' + ', '.join(missing) + '. Install them, or point the roles at CLIs you have (Settings, Roles).')
        if not self.start:
            lines += ['', f'Start it with: systemctl --user enable --now cursus   (or {binary} serve --config {self.config / "cursus.toml"})']
        return lines


def parser():
    root = argparse.ArgumentParser(prog='install.sh', description='Install Cursus for your own user and start it.')
    root.add_argument('--dry-run', action='store_true', help='print the plan; change nothing')
    root.add_argument('--yes', action='store_true', help='apply without asking (required when not interactive)')
    root.add_argument('--wheelhouse', metavar='DIR', help='install dependencies offline from this directory of wheels')
    root.add_argument('--origin', metavar='URL', help='the https origin you open the website at (default: from Tailscale)')
    root.add_argument('--operator-login', metavar='LOGIN', help='the identity allowed to use the website (default: from Tailscale)')
    root.add_argument('--no-start', action='store_true', help='install but do not enable or start the service')
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if os.geteuid() == 0:
        print('Run this as your own user, not as root: Cursus runs as the user whose CLI logins it uses, so a root '
              'install would use the wrong account. You do not need root: the one step that needs privileges, creating '
              'the PostgreSQL role and database, uses sudo by itself and asks for your password.', file=sys.stderr)
        return 1
    installer = Installer(wheelhouse=args.wheelhouse, origin=args.origin, operator_login=args.operator_login,
                          start=not args.no_start)
    try:
        installer.check()
        installer.access()
        found, missing = installer.cli_report()
        print('CLIs found on your PATH: ' + (', '.join(f'{c} ({p})' for c, p in sorted(found.items())) or 'none'))
        if missing:
            print('Not found on your PATH (needed by the default roles): ' + ', '.join(missing) +
                  '. Install and sign in to them, or point the roles at the CLIs you have on the website.')
        print('Plan:')
        for line in installer.plan():
            print('  - ' + line)
        if args.dry_run:
            print('Dry run: nothing was changed.')
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                print('Not interactive: pass --yes to apply these changes.', file=sys.stderr)
                return 1
            if input('Proceed? [y/N] ').strip().lower() not in ('y', 'yes'):
                print('Nothing was changed.')
                return 0
        installer.apply()
        print('\n'.join(installer.summary()))
        return 0
    except (InstallError, subprocess.CalledProcessError, OSError) as exc:
        print(f'Installation stopped: {exc}\nFiles already written are kept; rerunning is safe.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
