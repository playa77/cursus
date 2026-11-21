"""The per-user installer that finishes the job (ADR 0017, ADR 0018): offline, in a temporary HOME.

Every system interaction (pip, venv, tailscale, psql, sudo, systemctl, loginctl, journalctl, the service's
own status call) goes through one recorded fake; git is real (it only touches temporary directories) and
the produced configuration is loaded by the real loader. This establishes the installer's file, safety,
ordering and failure behavior. It does not exercise a real sudo, PostgreSQL, systemd session, tailnet or CLI.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tomllib
import unittest
from unittest.mock import patch
from tests.support import workspace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cursus_install', ROOT / 'deploy' / 'install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

REAL_RUN = subprocess.run       # the fake delegates git to this, even while subprocess.run is patched

TAILSCALE = {'BackendState': 'Running', 'Self': {'DNSName': 'box.tail1234.ts.net.', 'UserID': 7},
             'User': {'7': {'LoginName': 'me@example.com'}}}


class System:
    """Everything outside the temporary HOME, recorded and simulated."""

    def __init__(self):
        self.calls = []
        self.tailscale = dict(TAILSCALE)
        self.tailscale_rc = 0
        self.serve = {'TCP': {'443': {}}, 'Web': {'box:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8787'}}}}}
        self.db_ready = False          # postgresql:///cursus connects
        self.role_exists = False
        self.direct_admin = False      # may the user create roles itself?
        self.sudo_n = True             # passwordless sudo works
        self.sudo_prompt = True        # sudo with a password prompt works
        self.peer_broken = False       # database exists but the DSN still cannot connect
        self.service_active = False
        self.daemon_reload_rc = 0
        self.linger_rc = 0
        self.enable_rc = 0
        self.ready_after = 0           # status calls that fail before the service answers
        self.failed_state = False
        self.status_calls = 0

    def names(self):
        return [Path(c[0]).name for c in self.calls]

    def done(self, rc=0, out='', err=''):
        return subprocess.CompletedProcess([], rc, out, err)

    def psql(self, argv, via_sudo):
        target = argv[argv.index('-d') + 1]
        statement = argv[argv.index('-c') + 1]
        if target.startswith('postgresql:'):
            return self.done(0 if self.db_ready and not self.peer_broken else 2, '', 'FATAL: connection failed')
        if via_sudo is None and not self.direct_admin:
            return self.done(2, '', f'psql: FATAL: role "tester" does not exist')
        if via_sudo == 'n' and not self.sudo_n or via_sudo == 'prompt' and not self.sudo_prompt:
            return self.done(1, '', 'sudo: a password is required')
        if statement.startswith('SELECT 1 FROM pg_roles'):
            return self.done(0, '1\n' if self.role_exists else '')
        if statement.startswith('SELECT 1 FROM pg_database'):
            return self.done(0, '1\n' if self.db_ready else '')
        if statement.startswith('CREATE ROLE'):
            self.role_exists = True
        elif statement.startswith('CREATE DATABASE'):
            self.db_ready = True
        return self.done()

    def __call__(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        name = Path(argv[0]).name
        if name == 'git':
            return REAL_RUN(argv, **kwargs)
        if argv[1:3] == ['-m', 'venv']:
            python = Path(argv[3]) / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\n')
            python.chmod(0o755)
            return self.done()
        if argv[1:3] == ['-m', 'pip']:
            return self.done()
        if name == 'tailscale':
            if argv[1:3] == ['serve', 'status']:
                return self.done(0, json.dumps(self.serve))
            return self.done(self.tailscale_rc, json.dumps(self.tailscale), 'tailscaled is not running' if self.tailscale_rc else '')
        if name == 'sudo':
            mode = 'n' if argv[1] == '-n' else 'prompt'
            start = next(i for i, a in enumerate(argv) if Path(a).name == 'psql')
            return self.psql(argv[start:], mode)
        if name == 'psql':
            return self.psql(argv, None)
        if name == 'systemctl':
            verb = argv[2] if argv[1] == '--user' else argv[1]
            if verb == 'daemon-reload':
                return self.done(self.daemon_reload_rc, '', 'Failed to connect to bus: No medium found')
            if verb == 'is-active':
                if '--quiet' in argv:
                    return self.done(0 if self.service_active else 3)
                return self.done(0, 'failed\n' if self.failed_state else 'activating\n')
            if verb == 'enable':
                if not self.enable_rc:
                    self.service_active = True
                return self.done(self.enable_rc, '', 'Failed to enable unit')
        if name == 'loginctl':
            return self.done(self.linger_rc, '', 'Access denied')
        if name == 'journalctl':
            return self.done(0, 'cursus[1]: Replace every REPLACE_ placeholder\n')
        if name == 'cursus':
            self.status_calls += 1
            return self.done(0 if self.status_calls > self.ready_after else 1, '{}')
        raise AssertionError('Unexpected system call: ' + ' '.join(argv))


def which_for(*missing):
    real_git = shutil.which('git')
    return lambda name: None if name in missing else (real_git if name == 'git' else '/usr/bin/' + name)


def make(ws, system=None, **options):
    system = system or System()
    home = ws.root / 'home dir é'          # Spaces and non-ASCII must work.
    home.mkdir(exist_ok=True)
    meminfo = ws.root / 'meminfo'
    meminfo.write_text('MemTotal:       16384000 kB\n')
    values = dict(home=home, source=ROOT, run=system, which=which_for(), out=lambda *_: None, user='tester', group='testers',
                  runtime_dir='/run/user/4242', environ={'PATH': '/nonexistent'}, interactive=False,
                  sleep=lambda _: None, meminfo=str(meminfo))
    values.update(options)
    return install.Installer(**values), home, system


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class ApplyTests(unittest.TestCase):
    def test_a_fresh_install_produces_a_running_deployment_that_loads_without_any_operator_edit(self):
        from cursus.config import load
        with workspace() as ws:
            installer, home, system = make(ws)
            installer.access()
            installer.apply()
            config, state = home / '.config' / 'cursus', home / '.local' / 'state' / 'cursus'
            for directory in (config, state, *(state / n for n in ('state', 'artifacts', 'repositories', 'worktrees', 'reviews', 'backups'))):
                self.assertEqual(mode(directory), 0o700, directory)
            self.assertEqual(mode(config / 'cursus.toml'), 0o600)
            self.assertEqual((config / 'database-dsn').read_text(), 'postgresql:///cursus\n')
            self.assertTrue((home / '.config/systemd/user/cursus.service').is_file())
            settings = load('serve', str(config / 'cursus.toml'))          # the REAL loader accepts it as written
            self.assertEqual(settings['service']['external_origin'], 'https://box.tail1234.ts.net')
            self.assertEqual(settings['service']['operator_login'], 'me@example.com')
            self.assertEqual(settings['service']['role_release_commit'], git(config / 'roles', 'rev-parse', 'HEAD'))
            self.assertEqual(settings['repositories'], [])                  # idle until a repository is enrolled
            self.assertEqual(settings['unqualified_roles'], sorted(settings['roles']))   # models are the operator's choice
            self.assertEqual(system.service_active, True)

    def test_derived_values_are_conservative_bounded_and_reflect_this_machine(self):
        with workspace() as ws:
            tools = ws.root / 'tools'
            tools.mkdir()
            claude = tools / 'claude'
            claude.write_text('#!/bin/sh\n')
            claude.chmod(0o755)
            installer, home, _ = make(ws, environ={'PATH': f'{tools}:/nonexistent:relative/dir'})
            installer.access()
            installer.apply()
            data = tomllib.loads((home / '.config/cursus/cursus.toml').read_text())
            self.assertEqual(data['capacity'], {'worker': 2, 'claude': 1, 'codex': 1, 'agy': 1, 'verifier': 1, 'repository': 1})
            self.assertEqual(data['execution']['host_reserve_mb'], 1600)      # 10% of 16000 MB, within 512..4096
            self.assertTrue(512 <= data['execution']['disk_reserve_mb'] <= 5120)
            directories = data['execution']['path'].split(':')
            self.assertEqual(directories[0], str(tools))
            self.assertNotIn('/nonexistent', directories)
            self.assertNotIn('relative/dir', directories)
            self.assertEqual(data['execution']['pass_env'], ['XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'])
            self.assertEqual(data['service']['listen_port'], 8787)
            self.assertEqual(data['service']['operator_socket'], '/run/user/4242/cursus/operator.sock')
            self.assertEqual(len(data['runner']['id']), 36)

    def test_wheelhouse_makes_installation_offline(self):
        with workspace() as ws:
            installer, _, system = make(ws, wheelhouse=ws.root / 'wheels')
            installer.access()
            installer.apply()
            pip = [c for c in system.calls if c[1:3] == ['-m', 'pip']]
            self.assertIn('--require-hashes', pip[0])
            self.assertEqual(pip[0][pip[0].index('-r') + 1], str(ROOT / 'requirements.lock'))
            for command in pip:
                self.assertIn('--no-index', command)
                self.assertEqual(command[command.index('--find-links') + 1], str(ws.root / 'wheels'))

    def test_role_release_is_a_separate_git_repo_with_the_unedited_files_pinned_by_the_config(self):
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.access()
            installer.apply()
            roles = home / '.config' / 'cursus' / 'roles'
            self.assertEqual((roles / 'roles.toml').read_bytes(), (ROOT / 'roles.toml').read_bytes())
            self.assertEqual(sorted(p.name for p in (roles / 'prompts').glob('*.md')), sorted(p.name for p in (ROOT / 'prompts').glob('*.md')))
            self.assertEqual(git(roles, 'log', '--format=%s'), 'Initial role release (unedited)')

    def test_rerun_never_overwrites_operator_values_or_files(self):
        with workspace() as ws:
            installer, home, system = make(ws)
            installer.access()
            installer.apply()
            config, dsn = home / '.config/cursus/cursus.toml', home / '.config/cursus/database-dsn'
            config.write_text('# my own file\n[a]\nb = 1\n')
            dsn.write_text('postgresql://custom\n')
            system.db_ready = True
            system.calls.clear()
            installer.apply()
            self.assertEqual(config.read_text(), '# my own file\n[a]\nb = 1\n')
            self.assertEqual(dsn.read_text(), 'postgresql://custom\n')
            self.assertFalse(any(c[1:3] == ['-m', 'venv'] for c in system.calls))   # the environment is reused
            self.assertTrue(any(c[1:3] == ['-m', 'pip'] for c in system.calls))     # the package is refreshed

    def test_an_unfinished_zero_point_seven_config_is_completed_not_replaced(self):
        from cursus.config import load
        with workspace() as ws:
            installer, home, system = make(ws)
            installer.access()
            installer.apply()
            path = home / '.config/cursus/cursus.toml'
            data = tomllib.loads(path.read_text())
            data['service'].update(external_origin='https://REPLACE_HOST.REPLACE_TAILNET.ts.net', operator_login='REPLACE_EXACT_TAILSCALE_LOGIN',
                                   role_release_commit='REPLACE_FULL_RELEASE_COMMIT', listen_port=9000)
            data['capacity']['worker'] = 'REPLACE_WORKER_1_TO_4'
            data['execution']['disk_reserve_mb'] = 'REPLACE_POLICY_MB'
            data['limits']['repair_retries'] = 7                 # an operator's own choice must survive
            from cursus.tomlwrite import dumps
            path.write_text(dumps(data))
            installer.pin = None
            installer.apply()
            done = load('serve', str(path))
            self.assertEqual(done['service']['external_origin'], 'https://box.tail1234.ts.net')
            self.assertEqual((done['limits']['repair_retries'], done['service']['listen_port']), (7, 9000))
            self.assertEqual(done['capacity']['worker'], 2)
            self.assertEqual(len(list(path.parent.glob('cursus.toml.bak-*'))), 1)
            self.assertEqual(mode(next(path.parent.glob('cursus.toml.bak-*'))), 0o600)
            self.assertEqual(mode(path), 0o600)

    def test_uncommitted_role_edits_are_committed_and_pinned(self):
        from cursus.config import load
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.access()
            installer.apply()
            roles = home / '.config/cursus/roles'
            (roles / 'prompts' / 'worker.md').write_text('My own worker prompt.\n')
            path = home / '.config/cursus/cursus.toml'
            data = tomllib.loads(path.read_text())
            data['service']['role_release_commit'] = 'REPLACE_FULL_RELEASE_COMMIT'
            from cursus.tomlwrite import dumps
            path.write_text(dumps(data))
            installer.apply()
            self.assertIn('Installer: commit role edits', git(roles, 'log', '-1', '--format=%s'))
            self.assertEqual(load('serve', str(path))['roles']['worker']['prompt_text'], 'My own worker prompt.\n')

    def test_a_different_existing_unit_is_kept_and_the_new_one_written_beside_it(self):
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.access()
            unit = home / '.config/systemd/user/cursus.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('[Service]\nExecStart=/custom\n')
            messages = []
            installer.out = messages.append
            installer.apply()
            self.assertEqual(unit.read_text(), '[Service]\nExecStart=/custom\n')
            self.assertEqual((unit.parent / 'cursus.service.new').read_text(), (ROOT / 'deploy/cursus.service').read_text())
            self.assertTrue(any('cursus.service.new' in m for m in messages))

    def test_unit_matches_the_installed_layout_and_stops_the_whole_group(self):
        unit = (ROOT / 'deploy/cursus.service').read_text()
        self.assertIn('ExecStart="%h/.local/share/cursus/venv/bin/cursus" serve --config "%h/.config/cursus/cursus.toml"', unit)
        self.assertIn('KillMode=control-group', unit)
        self.assertIn('WantedBy=default.target', unit)
        self.assertIn('Restart=on-failure', unit)        # the website's restart exits with status 75


class AccessTests(unittest.TestCase):
    def test_origin_and_login_come_from_tailscale_and_the_installer_never_configures_it(self):
        with workspace() as ws:
            installer, _, system = make(ws)
            self.assertEqual(installer.access(), ('https://box.tail1234.ts.net', 'me@example.com'))
            self.assertIsNone(installer.serve_notice)
            self.assertTrue(all(c[1] in ('status', 'serve') and c[-1] in ('--json',) for c in system.calls if Path(c[0]).name == 'tailscale'))
            self.assertFalse(any(c[1] in ('up', 'login', 'set') or (c[1] == 'serve' and c[2] != 'status') for c in system.calls if Path(c[0]).name == 'tailscale'))

    def test_a_missing_serve_entry_is_a_notice_with_the_command_not_an_error_and_not_run(self):
        with workspace() as ws:
            system = System()
            system.serve = {}
            installer, home, _ = make(ws, system)
            installer.access()
            installer.apply()
            self.assertEqual(installer.serve_notice, 'tailscale serve --bg 8787')
            self.assertIn('tailscale serve --bg 8787', '\n'.join(installer.summary()))
            self.assertFalse(any(Path(c[0]).name == 'tailscale' and c[2:3] == ['--bg'] for c in system.calls))

    def test_flags_bypass_tailscale_entirely(self):
        with workspace() as ws:
            installer, _, system = make(ws, origin='https://x.example.org', operator_login='a@b.c')
            self.assertEqual(installer.access(), ('https://x.example.org', 'a@b.c'))
            self.assertEqual(system.calls, [])

    def test_every_tailscale_failure_stops_with_prose_before_anything_changes(self):
        cases = {
            'not installed': dict(which=which_for('tailscale')),
            'daemon down': dict(rc=1),
            'logged out': dict(status={**TAILSCALE, 'BackendState': 'NeedsLogin'}),
            'no MagicDNS name': dict(status={'BackendState': 'Running', 'Self': {'DNSName': '', 'UserID': 7}, 'User': {'7': {'LoginName': 'me@example.com'}}}),
            'tagged node': dict(status={'BackendState': 'Running', 'Self': {'DNSName': 'box.ts.net.', 'UserID': 0}, 'User': {}}),
            'garbage': dict(status='nonsense'),
        }
        for label, case in cases.items():
            with self.subTest(label), workspace() as ws:
                system = System()
                system.tailscale_rc = case.get('rc', 0)
                if 'status' in case:
                    system.tailscale = case['status']
                installer, home, _ = make(ws, system, **({'which': case['which']} if 'which' in case else {}))
                with self.assertRaises(install.InstallError) as caught:
                    installer.apply()
                text = str(caught.exception)
                self.assertIn('Nothing was changed', text)
                self.assertIn('--origin', text)
                self.assertIn('does not install, configure or sign in to Tailscale', text)
                self.assertEqual(list(home.iterdir()), [], label)


class DatabaseTests(unittest.TestCase):
    def run_apply(self, system, **options):
        with workspace() as ws:
            installer, home, _ = make(ws, system, **options)
            installer.access()
            installer.apply()
            return system

    def sudo_calls(self, system):
        return [c for c in system.calls if Path(c[0]).name == 'sudo']

    def test_an_already_working_database_needs_no_sudo_and_no_creation(self):
        system = System()
        system.db_ready = True
        self.run_apply(system)
        self.assertEqual(self.sudo_calls(system), [])

    def test_the_role_and_database_are_created_with_passwordless_sudo_when_the_user_cannot(self):
        system = System()
        self.run_apply(system)
        calls = self.sudo_calls(system)
        self.assertTrue(calls)
        self.assertTrue(all(c[:4] == ['sudo', '-n', '-u', 'postgres'] for c in calls))
        self.assertTrue(system.role_exists and system.db_ready)
        statements = [c[c.index('-c') + 1] for c in calls]
        self.assertIn('CREATE ROLE "tester" LOGIN', statements)
        self.assertIn('CREATE DATABASE cursus OWNER "tester"', statements)

    def test_the_user_is_tried_first_and_sudo_is_not_used_when_it_suffices(self):
        system = System()
        system.direct_admin = True
        self.run_apply(system)
        self.assertEqual(self.sudo_calls(system), [])
        self.assertTrue(system.db_ready)

    def test_a_sudo_password_is_requested_only_on_a_terminal(self):
        system = System()
        system.sudo_n = False
        with workspace() as ws:
            installer, _, _ = make(ws, system, interactive=False)
            installer.access()
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
            self.assertFalse(any(c[:3] == ['sudo', '-u', 'postgres'] for c in system.calls))
            self.assertIn('sudo -u postgres createuser tester', str(caught.exception))
        system = System()
        system.sudo_n = False
        self.run_apply(system, interactive=True)
        self.assertTrue(any(c[:3] == ['sudo', '-u', 'postgres'] for c in system.calls))
        self.assertTrue(system.db_ready)

    def test_failure_to_create_explains_the_cause_and_the_manual_commands(self):
        system = System()
        system.sudo_n = False
        with workspace() as ws:
            installer, home, _ = make(ws, system)
            installer.access()
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
        text = str(caught.exception)
        self.assertIn('could not be created', text)
        self.assertIn('a password is required', text)
        self.assertIn('pg_isready', text)
        self.assertIn('sudo -u postgres createdb -O tester cursus', text)

    def test_a_database_that_exists_but_does_not_connect_points_at_peer_authentication(self):
        system = System()
        system.peer_broken = True
        with workspace() as ws:
            installer, _, _ = make(ws, system)
            installer.access()
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
        self.assertIn('pg_hba.conf', str(caught.exception))

    def test_a_custom_dsn_that_does_not_connect_is_reported_not_provisioned(self):
        system = System()
        with workspace() as ws:
            installer, home, _ = make(ws, system)
            installer.access()
            (home / '.config/cursus').mkdir(parents=True)
            (home / '.config/cursus/database-dsn').write_text('postgresql://elsewhere/db\n')
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
            self.assertIn('cannot be reached', str(caught.exception))
            self.assertEqual(self.sudo_calls(system), [])

    def test_a_user_name_that_is_unsafe_in_sql_is_refused(self):
        with workspace() as ws:
            installer, _, system = make(ws, user='bad"name; DROP')
            installer.access()
            with self.assertRaises(install.InstallError):
                installer.apply()
            self.assertEqual(self.sudo_calls(system), [])


class LaunchTests(unittest.TestCase):
    def test_the_service_is_lingered_enabled_started_and_waited_for(self):
        with workspace() as ws:
            system = System()
            system.ready_after = 3
            installer, home, _ = make(ws, system)
            installer.access()
            installer.apply()
            self.assertIn(['/usr/bin/loginctl', 'enable-linger', 'tester'], system.calls)
            self.assertIn(['/usr/bin/systemctl', '--user', 'enable', '--now', 'cursus'], system.calls)
            self.assertEqual(system.status_calls, 4)

    def test_a_running_service_is_never_restarted_by_an_upgrade(self):
        with workspace() as ws:
            system = System()
            system.service_active = True
            messages = []
            installer, _, _ = make(ws, system, out=messages.append)
            installer.access()
            installer.apply()
            self.assertFalse(any('enable' in c for c in system.calls if Path(c[0]).name == 'systemctl'))
            self.assertFalse(any(Path(c[0]).name == 'systemctl' and 'restart' in c for c in system.calls))
            self.assertTrue(any('keeps running the version it started with' in m for m in messages))

    def test_no_start_installs_without_touching_services(self):
        with workspace() as ws:
            installer, _, system = make(ws, start=False, which=which_for('systemctl'))
            installer.access()
            installer.apply()
            self.assertFalse(any(Path(c[0]).name in ('loginctl',) or 'enable' in c for c in system.calls))
            self.assertIn('systemctl --user enable --now cursus', '\n'.join(installer.summary()))

    def test_no_user_session_is_explained_and_the_rest_is_kept(self):
        with workspace() as ws:
            system = System()
            system.daemon_reload_rc = 1
            installer, home, _ = make(ws, system)
            installer.access()
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
            text = str(caught.exception)
            self.assertIn('user session', text)
            self.assertIn('serve --config', text)
            self.assertTrue((home / '.config/cursus/cursus.toml').exists())

    def test_a_failed_linger_is_a_warning_with_the_command_not_a_failure(self):
        with workspace() as ws:
            system = System()
            system.linger_rc = 1
            messages = []
            installer, _, _ = make(ws, system, out=messages.append)
            installer.access()
            installer.apply()
            self.assertTrue(any('sudo loginctl enable-linger tester' in m for m in messages))
            self.assertTrue(system.service_active)

    def test_a_service_that_never_answers_reports_its_log(self):
        with workspace() as ws:
            system = System()
            system.ready_after = 10 ** 6
            system.failed_state = True
            installer, _, _ = make(ws, system)
            installer.access()
            with self.assertRaises(install.InstallError) as caught:
                installer.apply()
            self.assertIn('did not become ready', str(caught.exception))
            self.assertIn('Replace every REPLACE_ placeholder', str(caught.exception))

    def test_the_summary_names_the_address_and_exactly_what_is_left(self):
        with workspace() as ws:
            installer, _, _ = make(ws)
            installer.access()
            installer.apply()
            text = '\n'.join(installer.summary())
            for expected in ('https://box.tail1234.ts.net', 'me@example.com', 'Sign in to each CLI', 'Settings, Roles',
                             'Settings, Publisher'):
                self.assertIn(expected, text)


class PrerequisiteTests(unittest.TestCase):
    def test_missing_prerequisites_stop_before_any_change_with_an_explanation(self):
        for missing, expected in (('git', 'git is required'), ('psql', 'psql'), ('systemctl', '--no-start')):
            with self.subTest(missing), workspace() as ws:
                installer, home, system = make(ws, which=which_for(missing))
                with self.assertRaises(install.InstallError) as caught:
                    installer.check()
                self.assertIn(expected, str(caught.exception))
                self.assertEqual(system.calls, [])
                self.assertEqual(list(home.iterdir()), [])

    def test_a_broken_checkout_stops_before_any_change(self):
        with workspace() as ws:
            broken = ws.root / 'source'
            broken.mkdir()
            installer, home, system = make(ws, source=broken)
            with self.assertRaises(install.InstallError):
                installer.check()
            self.assertEqual(list(home.iterdir()), [])

    def test_cli_report_names_what_the_default_roles_use_without_blocking(self):
        with workspace() as ws:
            bin_dir = ws.root / 'bin'
            bin_dir.mkdir()
            claude = bin_dir / 'claude'
            claude.write_text('#!/bin/sh\n')
            claude.chmod(0o755)
            installer, *_ = make(ws, environ={'PATH': str(bin_dir)})
            found, missing = installer.cli_report()
            self.assertEqual(found['claude'], str(claude))
            self.assertEqual(set(missing), {'codex', 'agy', 'pi'} - set(found))


class CommandLineTests(unittest.TestCase):
    def run_main(self, ws, *argv, stdin_tty=False, euid=1000, system=None):
        out, err = io.StringIO(), io.StringIO()
        home = ws.root / 'h'
        home.mkdir(exist_ok=True)
        system = system or System()
        with patch.dict(os.environ, {'HOME': str(home), 'XDG_RUNTIME_DIR': '/run/user/4242'}), patch('os.geteuid', return_value=euid), \
                patch('sys.stdin.isatty', return_value=stdin_tty), patch('subprocess.run', system), \
                patch('shutil.which', which_for()), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = install.main(list(argv))
        return code, out.getvalue(), err.getvalue(), home

    def test_dry_run_prints_the_plan_including_the_derived_access_and_changes_nothing(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws, '--dry-run')
            self.assertEqual(code, 0, err)
            self.assertIn('Dry run', out)
            self.assertIn('cursus.toml', out)
            self.assertIn('https://box.tail1234.ts.net for me@example.com', out)
            self.assertIn('PostgreSQL: role', out)
            self.assertEqual(list(home.iterdir()), [])

    def test_root_is_refused_with_an_explanation_that_sudo_is_not_needed(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws, '--yes', euid=0)
            self.assertEqual(code, 1)
            self.assertIn('not as root', err)
            self.assertIn('uses sudo by itself', err)
            self.assertEqual(list(home.iterdir()), [])

    def test_changes_need_consent_when_not_interactive(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws)
            self.assertEqual(code, 1)
            self.assertIn('--yes', err)
            self.assertEqual(list(home.iterdir()), [])

    def test_unknown_arguments_are_rejected(self):
        with workspace() as ws:
            with self.assertRaises(SystemExit):
                self.run_main(ws, '--install-system-packages')

    def test_tailscale_failure_is_a_clean_error_exit_and_changes_nothing(self):
        with workspace() as ws:
            system = System()
            system.tailscale_rc = 1
            code, out, err, home = self.run_main(ws, '--yes', system=system)
            self.assertEqual(code, 1)
            self.assertIn('Nothing was changed', err)
            self.assertEqual(list(home.iterdir()), [])

    def test_a_full_run_ends_with_the_summary_and_exit_zero(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws, '--yes')
            self.assertEqual(code, 0, err)
            self.assertIn('Cursus is installed and running', out)
            self.assertIn('https://box.tail1234.ts.net', out)
            self.assertTrue((home / '.config/cursus/cursus.toml').exists())


if __name__ == '__main__':
    unittest.main()
