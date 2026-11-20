"""The per-user installer (ADR 0017): offline, in a temporary HOME, with pip/venv stubbed.

It establishes the installer's file, safety and consistency behavior. It does not
install real packages, talk to systemd or PostgreSQL, or touch a real CLI login.
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
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


def runner(calls):
    """Record every command; simulate venv creation; run git for real (it only touches temp dirs)."""
    def run(argv, **kwargs):
        argv = [str(a) for a in argv]
        calls.append(argv)
        if Path(argv[0]).name == 'git':
            return subprocess.run(argv, **kwargs)
        if argv[1:3] == ['-m', 'venv']:
            python = Path(argv[3]) / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\n')
            python.chmod(0o755)
        return subprocess.CompletedProcess(argv, 0)
    return run


def make(ws, calls=None, **options):
    calls = [] if calls is None else calls
    home = ws.root / 'home dir é'  # Spaces and non-ASCII must work.
    home.mkdir(exist_ok=True)
    values = dict(home=home, source=ROOT, run=runner(calls), which=lambda name: '/usr/bin/' + name if name == 'git' else None,
                  out=lambda *_: None, user='tester', group='testers', runtime_dir='/run/user/4242',
                  environ={'PATH': '/nonexistent'})
    values.update(options)
    return install.Installer(**values), home, calls


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class InstallerTests(unittest.TestCase):
    def test_apply_creates_private_directories_environment_config_roles_dsn_and_unit(self):
        with workspace() as ws:
            installer, home, calls = make(ws)
            installer.apply()
            config = home / '.config' / 'cursus'
            state = home / '.local' / 'state' / 'cursus'
            for directory in (config, state, *(state / n for n in ('state', 'artifacts', 'repositories', 'worktrees', 'reviews', 'backups'))):
                self.assertEqual(mode(directory), 0o700, directory)
            self.assertTrue((home / '.local/share/cursus/venv/bin/python').exists())
            self.assertEqual(mode(config / 'cursus.toml'), 0o600)
            self.assertEqual((config / 'database-dsn').read_text(), 'postgresql:///cursus\n')
            self.assertEqual(mode(config / 'database-dsn'), 0o600)
            self.assertTrue((home / '.config/systemd/user/cursus.service').is_file())
            pip = [c for c in calls if c[1:3] == ['-m', 'pip']]
            self.assertIn('--require-hashes', pip[0])
            self.assertEqual(pip[0][pip[0].index('-r') + 1], str(ROOT / 'requirements.lock'))
            self.assertEqual(pip[1][-1], str(ROOT))
            self.assertTrue({'--no-deps', '--no-build-isolation'} <= set(pip[1]))

    def test_wheelhouse_makes_installation_offline(self):
        with workspace() as ws:
            installer, _, calls = make(ws, wheelhouse=ws.root / 'wheels')
            installer.apply()
            pip = [c for c in calls if c[1:3] == ['-m', 'pip']]
            for command in pip:
                self.assertIn('--no-index', command)
                self.assertEqual(command[command.index('--find-links') + 1], str(ws.root / 'wheels'))

    def test_generated_config_fills_only_mechanical_values(self):
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.apply()
            text = (home / '.config/cursus/cursus.toml').read_text()
            config = tomllib.loads(text)
            service = config['service']
            self.assertEqual((service['user'], service['operator_group']), ('tester', 'testers'))
            self.assertEqual(service['operator_socket'], '/run/user/4242/cursus/operator.sock')
            self.assertEqual(service['state_root'], str(home / '.local/state/cursus/state'))
            self.assertEqual(service['roles_file'], str(home / '.config/cursus/roles/roles.toml'))
            self.assertEqual(service['dsn_file'], str(home / '.config/cursus/database-dsn'))
            self.assertEqual(len(config['runner']['id']), 36)
            # Everything else is a decision for the operator: nothing is defaulted for them.
            from cursus.config import placeholders
            self.assertEqual(set(placeholders(config)), {
                'service.external_origin', 'service.operator_login', 'service.role_release_commit',
                'capacity.worker', 'capacity.claude', 'capacity.codex', 'capacity.agy',
                'execution.disk_reserve_mb', 'execution.host_reserve_mb'})

    def test_rerun_never_overwrites_operator_files(self):
        with workspace() as ws:
            installer, home, calls = make(ws)
            installer.apply()
            config, dsn = home / '.config/cursus/cursus.toml', home / '.config/cursus/database-dsn'
            roles = home / '.config/cursus/roles/roles.toml'
            config.write_text('# edited by the operator\n')
            dsn.write_text('postgresql://custom\n')
            roles.write_text('# edited roles\n')
            calls.clear()
            installer.apply()
            self.assertEqual(config.read_text(), '# edited by the operator\n')
            self.assertEqual(dsn.read_text(), 'postgresql://custom\n')
            self.assertEqual(roles.read_text(), '# edited roles\n')
            self.assertFalse(any(c[1:3] == ['-m', 'venv'] for c in calls))  # The environment is reused.
            self.assertTrue(any(c[1:3] == ['-m', 'pip'] for c in calls))    # The package is refreshed.

    def test_a_different_existing_unit_is_kept_and_the_new_one_written_beside_it(self):
        with workspace() as ws:
            installer, home, _ = make(ws)
            unit = home / '.config/systemd/user/cursus.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('[Service]\nExecStart=/custom\n')
            messages = []
            installer.out = messages.append
            installer.apply()
            self.assertEqual(unit.read_text(), '[Service]\nExecStart=/custom\n')
            self.assertEqual((unit.parent / 'cursus.service.new').read_text(), (ROOT / 'deploy/cursus.service').read_text())
            self.assertTrue(any('cursus.service.new' in m for m in messages))

    def test_systemd_is_reloaded_only_when_available(self):
        with workspace() as ws:
            installer, _, calls = make(ws, which=lambda name: '/usr/bin/' + name)
            installer.apply()
            self.assertIn(['/usr/bin/systemctl', '--user', 'daemon-reload'], calls)
            installer, _, calls = make(ws, which=lambda name: '/usr/bin/git' if name == 'git' else None)
            installer.apply()
            self.assertFalse(any('systemctl' in c[0] for c in calls))

    def test_role_release_is_a_separate_git_repo_with_the_unedited_files(self):
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.apply()
            roles = home / '.config/cursus/roles'
            self.assertEqual((roles / 'roles.toml').read_bytes(), (ROOT / 'roles.toml').read_bytes())
            self.assertEqual(sorted(p.name for p in (roles / 'prompts').glob('*.md')),
                             sorted(p.name for p in (ROOT / 'prompts').glob('*.md')))
            log = subprocess.run(['git', '-C', str(roles), 'log', '--format=%s'], capture_output=True, text=True, check=True).stdout
            self.assertEqual(log.strip(), 'Initial role release (unedited)')

    def test_installer_output_plus_the_documented_edits_loads_through_the_real_loader(self):
        """The README's operator steps, executed: fill the policy values, qualify roles, commit, load."""
        from cursus.config import load
        with workspace() as ws:
            installer, home, _ = make(ws)
            installer.apply()
            roles = home / '.config/cursus/roles'
            text = (roles / 'roles.toml').read_text()
            for old, new in {'REPLACE_QUALIFIED_MODEL': 'model-1', 'REPLACE_QUALIFIED_REASONING': 'medium',
                             'REPLACE_QUALIFIED_OPENCODE_GO_PROVIDER_ID': 'provider-1'}.items():
                text = text.replace(old, new)
            (roles / 'roles.toml').write_text(text)
            git = ['git', '-c', 'user.name=Op', '-c', 'user.email=op@localhost', '-C', str(roles)]
            subprocess.run([*git, 'commit', '-qam', 'Qualified roles'], check=True)
            commit = subprocess.run([*git, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
            from tests.support import toml_text
            path = home / '.config/cursus/cursus.toml'
            value = tomllib.loads(path.read_text())
            value['service'].update(external_origin='https://host.example.ts.net', operator_login='me@example.com',
                                    role_release_commit=commit)
            value['capacity'].update(worker=2, claude=1, codex=1, agy=1)
            value['execution'].update(disk_reserve_mb=2048, host_reserve_mb=1024)
            path.write_text(toml_text(value))
            settings = load('serve', str(path))
            self.assertEqual(settings['repositories'], [])          # Idle until a repository is enrolled.
            self.assertEqual(settings['capacity']['worker'], 2)
            self.assertEqual(settings['roles']['worker']['cli'], 'pi')

    def test_unit_matches_the_installed_layout_and_stops_the_whole_group(self):
        unit = (ROOT / 'deploy/cursus.service').read_text()
        self.assertIn('ExecStart="%h/.local/share/cursus/venv/bin/cursus" serve --config "%h/.config/cursus/cursus.toml"', unit)
        self.assertIn('KillMode=control-group', unit)
        self.assertIn('WantedBy=default.target', unit)


class PrerequisiteTests(unittest.TestCase):
    def test_missing_git_or_source_files_stop_before_any_change(self):
        with workspace() as ws:
            installer, home, calls = make(ws, which=lambda name: None)
            with self.assertRaises(install.InstallError) as caught:
                installer.check()
            self.assertIn('git', str(caught.exception))
            broken = ws.root / 'source'
            broken.mkdir()
            installer, home, calls = make(ws, source=broken)
            with self.assertRaises(install.InstallError):
                installer.check()
            self.assertFalse(calls)
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
            self.assertEqual(found, {'claude': str(claude)})
            self.assertEqual(set(missing), {'codex', 'agy', 'pi'})


class CommandLineTests(unittest.TestCase):
    def run_main(self, ws, *argv, stdin_tty=False, euid=1000):
        out, err = io.StringIO(), io.StringIO()
        home = ws.root / 'h'
        home.mkdir(exist_ok=True)
        with patch.dict(os.environ, {'HOME': str(home)}), patch('os.geteuid', return_value=euid), \
                patch('sys.stdin.isatty', return_value=stdin_tty), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = install.main(list(argv))
        return code, out.getvalue(), err.getvalue(), home

    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws, '--dry-run')
            self.assertEqual(code, 0, err)
            self.assertIn('Dry run', out)
            self.assertIn('cursus.toml', out)
            self.assertEqual(list(home.iterdir()), [])

    def test_root_is_refused(self):
        with workspace() as ws:
            code, out, err, home = self.run_main(ws, '--yes', euid=0)
            self.assertEqual(code, 1)
            self.assertIn('not as root', err)
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


if __name__ == '__main__':
    unittest.main()
