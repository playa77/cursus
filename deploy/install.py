#!/usr/bin/env python3
"""Per-user Cursus installer (ADR 0017).

Runs as the user whose already-installed, already-signed-in CLIs Cursus will use. It
needs no root, installs no system packages, provisions no database, and never starts a
service, signs in to a CLI or touches a credential. It never overwrites an existing
operator file. Policy values (capacity, reserves, repositories, origin, login) are left
for the operator to choose; only mechanical values are filled in.
"""
import argparse
import os
from pathlib import Path
import pwd
import grp
import shlex
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
STATE_DIRECTORIES = ('state', 'artifacts', 'repositories', 'worktrees', 'reviews', 'backups')
SOURCE_FILES = ('requirements.lock', 'pyproject.toml', 'roles.toml', 'deploy/cursus.example.toml', 'deploy/cursus.service')


class InstallError(Exception):
    pass


def toml_escape(text):
    return str(text).replace('\\', '\\\\').replace('"', '\\"')


class Installer:
    def __init__(self, home=None, source=None, run=subprocess.run, which=shutil.which, out=print,
                 user=None, group=None, runtime_dir=None, wheelhouse=None, environ=None):
        self.home = Path(home) if home else Path.home()
        self.source = Path(source) if source else ROOT
        self.run, self.which, self.out = run, which, out
        self.environ = os.environ if environ is None else environ
        self.user = user or pwd.getpwuid(os.getuid()).pw_name
        self.group = group or grp.getgrgid(os.getgid()).gr_name
        self.runtime_dir = runtime_dir or self.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
        self.wheelhouse = Path(wheelhouse) if wheelhouse else None
        self.config = self.home / '.config' / 'cursus'
        self.state = self.home / '.local' / 'state' / 'cursus'
        self.venv = self.home / '.local' / 'share' / 'cursus' / 'venv'
        self.unit = self.home / '.config' / 'systemd' / 'user' / 'cursus.service'

    # --- checks and reporting (no side effects) ---------------------------------------------

    def check(self):
        if sys.version_info < (3, 12):
            raise InstallError('Python 3.12 or newer is required.')
        if not self.which('git'):
            raise InstallError('git is required (for the role release and the checkout).')
        missing = [name for name in SOURCE_FILES if not (self.source / name).is_file()]
        if missing or not (self.source / 'prompts').is_dir():
            raise InstallError('This does not look like a Cursus checkout; missing: ' + ', '.join(missing or ['prompts/']))

    def cli_report(self):
        """Which CLIs the default roles use are findable on this user's PATH (informational)."""
        sys.path.insert(0, str(self.source / 'src'))
        try:
            from cursus.recipes import EXECUTABLES, discover
        finally:
            sys.path.pop(0)
        search = [d for d in self.environ.get('PATH', '').split(':') if d.startswith('/')]
        found = discover({'path': ':'.join(search) or '/usr/bin'})
        return found, sorted(set(EXECUTABLES) - set(found))

    def plan(self):
        def state(path):
            return 'kept, already exists' if path.exists() else 'created'
        lines = [
            f'Private directories: {self.config}, {self.state} (mode 0700)',
            f'Python environment {self.venv}: ' + ('reused' if (self.venv / 'bin' / 'python').exists() else 'created')
            + '; hash-checked packages from requirements.lock' + (f' (offline from {self.wheelhouse})' if self.wheelhouse else '')
            + ' and this checkout refreshed',
            f'Role release {self.config / "roles"}: {state(self.config / "roles")} (its own git repo, unedited files)',
            f'Database DSN file {self.config / "database-dsn"}: {state(self.config / "database-dsn")}',
            f'Configuration {self.config / "cursus.toml"}: {state(self.config / "cursus.toml")}'
            + ('' if (self.config / 'cursus.toml').exists() else ' (mechanical values filled; policy values left for you)'),
            f'User service unit {self.unit}: ' + ('kept; a differing new one is written beside it' if self.unit.exists() else 'created'),
        ]
        return lines

    def next_steps(self):
        config, roles, binary = self.config / 'cursus.toml', self.config / 'roles', self.venv / 'bin' / 'cursus'
        q = shlex.quote
        return [
            'Nothing has been started or signed in. Next, in order:',
            f'  1. Sign in to each CLI your roles use (claude, codex, agy, pi) as {self.user}. Cursus never does this.',
            f'  2. Create the database once:  sudo -u postgres createuser {q(self.user)} && sudo -u postgres createdb -O {q(self.user)} cursus',
            f'  3. Qualify the roles: edit {roles / "roles.toml"} (model, reasoning, provider), then',
            f'       git -C {q(str(roles))} commit -am "Qualified roles" && git -C {q(str(roles))} rev-parse HEAD',
            '     and put that commit in service.role_release_commit.',
            f'  4. Edit {config}: fill every REPLACE_ value (loading tells you which remain) and set [execution] path',
            '     to the directories holding your CLIs.',
            f'  5. Check the installs:  {q(str(binary))} preflight --roles {q(str(roles / "roles.toml"))} --config {q(str(config))}',
            f'  6. Run once in the foreground to validate:  {q(str(binary))} serve --config {q(str(config))}   (Ctrl-C stops)',
            f'  7. Run as a service:  loginctl enable-linger {q(self.user)} && systemctl --user enable --now cursus',
        ]

    # --- changes ----------------------------------------------------------------------------

    def apply(self):
        self.check()
        self.directories()
        self.environment()
        self.roles()
        self.dsn()
        self.configuration()
        self.service_unit()

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

    def roles(self):
        target = self.config / 'roles'
        if target.exists():
            self.out(f'Kept the existing role release {target}.')
            return
        (target / 'prompts').mkdir(parents=True)
        shutil.copy2(self.source / 'roles.toml', target / 'roles.toml')
        for prompt in sorted((self.source / 'prompts').glob('*.md')):
            shutil.copy2(prompt, target / 'prompts' / prompt.name)
        git = self.which('git')
        base = [git, '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                '-c', 'user.name=Cursus', '-c', 'user.email=cursus@localhost', '-C', str(target)]
        self.run([*base, 'init', '-q'], check=True)
        self.run([*base, 'add', '.'], check=True)
        self.run([*base, 'commit', '-q', '-m', 'Initial role release (unedited)'], check=True)
        self.out(f'Created the role release {target} (unedited; qualify it before use).')

    def dsn(self):
        path = self.config / 'database-dsn'
        if path.exists():
            self.out(f'Kept the existing {path}.')
        else:
            # Peer authentication over the local socket as this user: the file holds no secret.
            self.private_file(path, 'postgresql:///cursus\n')
            self.out(f'Wrote {path} (local PostgreSQL socket, this user, database "cursus").')

    def configuration(self):
        path = self.config / 'cursus.toml'
        if path.exists():
            self.out(f'Kept the existing {path}.')
            return
        text = (self.source / 'deploy' / 'cursus.example.toml').read_text(encoding='utf-8')
        for token, value in {'REPLACE_SIGNED_IN_USER': self.user, 'REPLACE_GROUP': self.group,
                             'REPLACE_RUNTIME_DIR': self.runtime_dir, 'REPLACE_HOME': str(self.home),
                             'REPLACE_SOURCE': str(self.config / 'roles'), 'REPLACE_RUNNER_UUID': str(uuid4())}.items():
            text = text.replace(token, toml_escape(value))
        self.private_file(path, text)
        self.out(f'Wrote {path}: mechanical values filled; the policy values are yours to choose.')

    def service_unit(self):
        wanted = (self.source / 'deploy' / 'cursus.service').read_text(encoding='utf-8')
        self.unit.parent.mkdir(parents=True, exist_ok=True)
        if not self.unit.exists():
            self.unit.write_text(wanted, encoding='utf-8')
            self.out(f'Installed {self.unit} (not enabled or started).')
        elif self.unit.read_text(encoding='utf-8') != wanted:
            beside = self.unit.with_name(self.unit.name + '.new')
            beside.write_text(wanted, encoding='utf-8')
            self.out(f'Kept your existing {self.unit}; the shipped unit is at {beside} for you to compare.')
        systemctl = self.which('systemctl')
        if systemctl:
            result = self.run([systemctl, '--user', 'daemon-reload'], check=False)
            if getattr(result, 'returncode', 0):
                self.out('systemctl --user daemon-reload failed (no user session here?); run it yourself later.')


def parser():
    root = argparse.ArgumentParser(prog='install.sh', description='Install Cursus for your own user (no root needed).')
    root.add_argument('--dry-run', action='store_true', help='print the plan; change nothing')
    root.add_argument('--yes', action='store_true', help='apply without asking (required when not interactive)')
    root.add_argument('--wheelhouse', metavar='DIR', help='install dependencies offline from this directory of wheels')
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if os.geteuid() == 0:
        print('Run this as your own user, not as root: Cursus uses the CLIs signed in as that user.', file=sys.stderr)
        return 1
    installer = Installer(wheelhouse=args.wheelhouse)
    try:
        installer.check()
        found, missing = installer.cli_report()
        print('CLIs found on your PATH: ' + (', '.join(f'{c} ({p})' for c, p in sorted(found.items())) or 'none'))
        if missing:
            print('Not found on your PATH (needed by the default roles): ' + ', '.join(missing) +
                  '. Install and sign in to them, or edit the roles to use only what you have.')
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
        print()
        print('\n'.join(installer.next_steps()))
        return 0
    except (InstallError, subprocess.CalledProcessError, OSError) as exc:
        print(f'Installation stopped: {exc}. Files already written are kept; rerunning is safe.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
