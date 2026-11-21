"""Validated, atomic, backed-up configuration and role-release changes (ADR 0018).

Real loader, real git (temporary directories only), no database, no CLI, no network.
"""
import os
from pathlib import Path
import stat
import subprocess
import tomllib
import unittest
from unittest.mock import patch
from cursus.admin import Admin, FormProblem
from cursus.config import load
from cursus.contracts import Problem
from tests.support import serve_config, workspace


def make(ws, qualified=True, supervised=False):
    path, release, commit, _ = serve_config(ws, 'postgresql:///unused', qualified=qualified)
    settings = load('serve', str(path))
    return Admin(settings, supervised=supervised), path, release, settings


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class SectionTests(unittest.TestCase):
    def test_save_validates_backs_up_and_marks_pending_without_touching_the_running_view(self):
        with workspace() as ws:
            admin, path, _, settings = make(ws)
            self.assertEqual(admin.pending(), [])
            changed = admin.save_section('capacity', {'capacity.worker': '3', 'capacity.claude': '2',
                                                      'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            self.assertEqual(changed, ['capacity.worker', 'capacity.claude'])
            on_disk = tomllib.loads(path.read_text())
            self.assertEqual((on_disk['capacity']['worker'], on_disk['capacity']['claude']), (3, 2))
            self.assertEqual(settings['capacity']['worker'], 2)          # the running view is unchanged
            self.assertEqual(admin.pending(), ['capacity.claude', 'capacity.worker'])
            self.assertEqual(len(admin.history()), 1)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((admin.backup_root / admin.history()[0]['name']).stat().st_mode), 0o600)
            load('serve', str(path))                                      # and the saved file still loads

    def test_an_unchanged_form_writes_nothing(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            before = path.read_bytes()
            self.assertEqual(admin.save_section('capacity', admin.values('capacity'), 'op'), [])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(admin.history(), [])

    def test_invalid_values_name_each_field_and_change_nothing(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            before = path.read_bytes()
            with self.assertRaises(FormProblem) as caught:
                admin.save_section('capacity', {'capacity.worker': '9', 'capacity.claude': 'x',
                                                'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            self.assertEqual(set(caught.exception.errors), {'capacity.worker', 'capacity.claude'})
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(path.with_name('.cursus.toml.candidate').exists())

    def test_a_candidate_the_loader_rejects_is_never_installed(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            before = path.read_bytes()
            with patch('cursus.admin.config.load', side_effect=Problem('invalid_config', 'Loader says no.')):
                with self.assertRaises(FormProblem) as caught:
                    admin.save_section('capacity', {'capacity.worker': '3', 'capacity.claude': '1',
                                                    'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            self.assertIn('Loader says no.', caught.exception.message)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(admin.history(), [])
            self.assertFalse(path.with_name('.cursus.toml.candidate').exists())

    def test_optional_values_are_removed_when_blank_and_clis_table_disappears(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            form = admin.values('resources')
            form.update({'execution.path': '/usr/local/bin:/usr/bin', 'execution.clis.claude': '/opt/claude',
                         'execution.pass_env': 'XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS'})
            admin.save_section('resources', form, 'op')
            data = tomllib.loads(path.read_text())['execution']
            self.assertEqual(data['clis'], {'claude': '/opt/claude'})
            self.assertEqual(data['pass_env'], ['XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'])
            form.update({'execution.path': '', 'execution.clis.claude': '', 'execution.pass_env': ''})
            admin.save_section('resources', form, 'op')
            data = tomllib.loads(path.read_text())['execution']
            self.assertNotIn('clis', data)
            self.assertNotIn('path', data)
            self.assertNotIn('pass_env', data)

    def test_access_rejects_a_non_origin_and_an_unknown_group(self):
        with workspace() as ws:
            admin, _, _, _ = make(ws)
            form = admin.values('access')
            with self.assertRaises(FormProblem) as caught:
                admin.save_section('access', dict(form, **{'service.external_origin': 'http://x.invalid/path', 'service.listen_port': '8787',
                                                           'service.operator_group': 'no-such-group-here'}), 'op')
            self.assertEqual(set(caught.exception.errors), {'service.external_origin', 'service.operator_group'})

    def test_hand_edits_since_startup_are_kept_by_a_later_save(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            data = tomllib.loads(path.read_text())
            data['limits']['repair_retries'] = 7
            from cursus.tomlwrite import dumps
            path.write_text(dumps(data))
            admin.save_section('capacity', {'capacity.worker': '1', 'capacity.claude': '1',
                                            'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            self.assertEqual(tomllib.loads(path.read_text())['limits']['repair_retries'], 7)

    def test_restore_reinstalls_a_backup_through_the_same_validation(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            original = tomllib.loads(path.read_text())['capacity']['worker']
            admin.save_section('capacity', {'capacity.worker': '4', 'capacity.claude': '1',
                                            'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            backup = admin.history()[0]['name']
            admin.restore(backup)
            self.assertEqual(tomllib.loads(path.read_text())['capacity']['worker'], original)
            for bad in ('../cursus.toml', 'cursus-1.toml', ''):
                with self.assertRaises(Problem):
                    admin.restore(bad)

    def test_backups_are_pruned_to_a_bound(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            with patch('cursus.admin.BACKUPS_KEPT', 3):
                for number in (1, 2, 3, 4, 1, 2):
                    admin.save_section('capacity', {'capacity.worker': str(number), 'capacity.claude': '1',
                                                    'capacity.codex': '1', 'capacity.agy': '1'}, 'op')
            self.assertEqual(len(admin.history()), 3)


def repository_form(**overrides):
    form = {'owner': 'acme', 'name': 'widgets', 'object_format': 'sha1', 'allowed_target_refs': 'refs/heads/main',
            'phase_check_ids': 'unit', 'check_rows': '2', 'check.0.id': 'unit',
            'check.0.argv': '/usr/bin/python3\n-m\nunittest', 'check.0.cwd': '.', 'check.0.timeout_seconds': '300',
            'check.1.id': '', 'check.1.argv': ''}
    form.update(overrides)
    return form


class RepositoryTests(unittest.TestCase):
    def test_enroll_update_and_remove_keep_the_file_loadable(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            admin.save_repository(repository_form())
            repo = admin.repository('acme', 'widgets')
            self.assertEqual(repo['checks'][0]['argv'], ['/usr/bin/python3', '-m', 'unittest'])
            self.assertEqual(len(load('serve', str(path))['repositories']), 2)
            admin.save_repository(repository_form(allowed_target_refs='refs/heads/main\nrefs/heads/dev'), existing=repo)
            self.assertEqual(admin.repository('acme', 'widgets')['allowed_target_refs'], ['refs/heads/main', 'refs/heads/dev'])
            admin.remove_repository('acme', 'widgets')
            self.assertIsNone(admin.repository('acme', 'widgets'))
            self.assertEqual(len(load('serve', str(path))['repositories']), 1)

    def test_removing_the_last_repository_leaves_a_valid_idle_deployment(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            admin.remove_repository('fixture', 'repo')
            self.assertEqual(load('serve', str(path))['repositories'], [])

    def test_every_form_problem_is_reported_at_once(self):
        with workspace() as ws:
            admin, path, _, _ = make(ws)
            before = path.read_bytes()
            bad = repository_form(owner='bad owner', allowed_target_refs='main', phase_check_ids='nope',
                                  **{'check.0.argv': 'python3\n-m', 'check.0.timeout_seconds': '0', 'check.0.cwd': '../x'})
            with self.assertRaises(FormProblem) as caught:
                admin.save_repository(bad)
            self.assertTrue({'owner', 'allowed_target_refs', 'phase_check_ids', 'check.0.argv',
                             'check.0.timeout_seconds', 'check.0.cwd'} <= set(caught.exception.errors))
            self.assertEqual(path.read_bytes(), before)

    def test_duplicates_and_checkless_repositories_are_refused(self):
        with workspace() as ws:
            admin, _, _, _ = make(ws)
            with self.assertRaises(FormProblem):
                admin.save_repository(repository_form(owner='fixture', name='repo'))
            with self.assertRaises(FormProblem) as caught:
                admin.save_repository(repository_form(**{'check.0.id': '', 'check.0.argv': ''}))
            self.assertIn('checks', caught.exception.errors)


class RoleTests(unittest.TestCase):
    def role_form(self, admin, name, **overrides):
        role = admin.roles_view()[name]
        form = {'tier': role['tier'], 'cli': role['cli'], 'model': 'model-x', 'reasoning': 'medium',
                'provider': role.get('provider', ''), 'timeout_seconds': str(role['timeout_seconds']),
                'prompt': role['prompt']}
        if 'REPLACE_' in form['provider']:
            form['provider'] = 'prov-x'
        for tool in role['tools']:
            form['tool.' + tool] = 'on'
        form.update(overrides)
        return form

    def test_unqualified_roles_still_load_and_are_listed_as_incomplete(self):
        with workspace() as ws:
            admin, path, _, settings = make(ws, qualified=False)
            self.assertEqual(settings['unqualified_roles'], sorted(settings['roles']))
            self.assertNotIn('qualified', settings['roles']['planner'])   # role dicts travel in strict job snapshots
            self.assertTrue(settings['roles']['worker']['provider'].startswith('REPLACE_'))
            holes = {n for n, r in admin.roles_view().items() if not r['qualified']}
            self.assertEqual(holes, set(settings['roles']))
            items = {i.key: i for i in admin.checklist()}
            self.assertEqual(items['roles'].state, 'todo')

    def test_saving_a_role_commits_pins_and_stays_loadable(self):
        with workspace() as ws:
            admin, path, release, _ = make(ws, qualified=False)
            before = git(release, 'rev-parse', 'HEAD')
            commit = admin.save_role('planner', self.role_form(admin, 'planner'), 'op@example.invalid')
            self.assertNotEqual(commit, before)
            self.assertEqual(git(release, 'rev-parse', 'HEAD'), commit)
            self.assertEqual(tomllib.loads(path.read_text())['service']['role_release_commit'], commit)
            self.assertIn('changed on the website by op@example.invalid', git(release, 'log', '-1', '--format=%s'))
            self.assertIn('service.role_release_commit', admin.pending())
            loaded = load('serve', str(path))
            self.assertNotIn('planner', loaded['unqualified_roles'])
            self.assertEqual(loaded['roles']['planner']['model'], 'model-x')
            self.assertIn('worker', loaded['unqualified_roles'])
            self.assertEqual(admin.release_state(), dict(pin=commit, head=commit, dirty=False, differs=False))

    def test_invalid_roles_are_rejected_before_anything_is_written(self):
        with workspace() as ws:
            admin, path, release, _ = make(ws)
            head = git(release, 'rev-parse', 'HEAD')
            before = (release / 'roles.toml').read_bytes()
            cases = [dict(model='-bad'), dict(reasoning='has space'), dict(cli='nope'),
                     dict(cli='claude', tier='production'),              # production requires pi
                     {'tool.bash': 'on', 'tier': 'organization', 'cli': 'claude'},  # organization is read-only
                     dict(prompt='../evil.md'), dict(timeout_seconds='0')]
            for overrides in cases:
                with self.assertRaises(FormProblem, msg=overrides):
                    admin.save_role('planner', self.role_form(admin, 'planner', **overrides), 'op')
            self.assertEqual(git(release, 'rev-parse', 'HEAD'), head)
            self.assertEqual((release / 'roles.toml').read_bytes(), before)

    def test_a_pin_failure_reverts_the_release_without_discarding_history(self):
        with workspace() as ws:
            admin, path, release, _ = make(ws)
            pinned = tomllib.loads(path.read_text())['service']['role_release_commit']
            with patch.object(Admin, 'commit_config', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    admin.save_role('planner', self.role_form(admin, 'planner'), 'op')
            self.assertEqual(tomllib.loads(path.read_text())['service']['role_release_commit'], pinned)
            self.assertEqual(git(release, 'rev-list', '--count', 'HEAD'), '3')      # fixture + change + revert
            load('serve', str(path))                                            # files equal the pinned release again

    def test_saving_a_prompt_commits_and_pins_it(self):
        with workspace() as ws:
            admin, path, release, _ = make(ws)
            commit = admin.save_prompt('planner.md', 'New planner prompt.\n', 'op')
            self.assertEqual(load('serve', str(path))['roles']['planner']['prompt_text'], 'New planner prompt.\n')
            self.assertEqual(git(release, 'rev-parse', 'HEAD'), commit)
            self.assertIsNone(admin.save_prompt('planner.md', 'New planner prompt.\n', 'op'))
            with self.assertRaises(FormProblem):
                admin.save_prompt('planner.md', '   ', 'op')
            with self.assertRaises(Problem):
                admin.save_prompt('../x.md', 'x', 'op')

    def test_hand_edited_roles_are_pinned_only_after_validation(self):
        with workspace() as ws:
            admin, path, release, _ = make(ws)
            (release / 'prompts' / 'judge.md').write_text('Hand edited.\n')
            self.assertTrue(admin.release_state()['dirty'])
            with self.assertRaises(Problem):
                load('serve', str(path))                # the service would refuse to start: files differ from the pin
            commit = admin.pin_current('op')
            self.assertEqual(load('serve', str(path))['roles']['judge']['prompt_text'], 'Hand edited.\n')
            self.assertFalse(admin.release_state()['dirty'])
            self.assertEqual(git(release, 'rev-parse', 'HEAD'), commit)
            (release / 'roles.toml').write_text('schema_version = 2\n[roles]\n')
            with self.assertRaises(FormProblem):
                admin.pin_current('op')                 # invalid hand edits are never committed


class CredentialAndRestartTests(unittest.TestCase):
    def test_token_is_written_privately_and_never_reported(self):
        with workspace() as ws:
            admin, _, _, _ = make(ws)
            self.assertFalse(any(s['present'] for s in admin.credential_status().values()))
            secret = 'ghp_ExampleToken_1234567890'
            admin.set_token(secret)
            status = admin.credential_status()
            self.assertTrue(all(s['present'] and s['private'] for s in status.values()))
            self.assertNotIn(secret, repr(status))
            github = Path(status['github_credential_file']['path'])
            self.assertEqual(github.read_text(), secret + '\n')
            self.assertEqual(stat.S_IMODE(github.stat().st_mode), 0o600)
            self.assertEqual(Path(status['git_credential_file']['path']).read_text(),
                             f'https://x-access-token:{secret}@github.com\n')
            self.assertEqual({i.key: i.state for i in admin.checklist()}['token'], 'ok')
            for bad in ('', 'short', 'has space in it', 'a@b:c/d' * 3, 'x' * 300):
                with self.assertRaises(FormProblem) as caught:
                    admin.set_token(bad)
                self.assertNotIn(bad or 'x', caught.exception.message) if bad else None

    def test_restart_is_refused_unless_supervised_and_calls_the_hook_when_it_is(self):
        with workspace() as ws:
            admin, _, _, _ = make(ws, supervised=False)
            with self.assertRaises(Problem):
                admin.request_restart()
            self.assertFalse(admin.restart_requested)
            admin.supervised = True
            calls = []
            admin.restart_hook = lambda: calls.append(1)
            admin.request_restart()
            self.assertTrue(admin.restart_requested)
            self.assertEqual(calls, [1])

    def test_checklist_reports_pending_restart_and_enrollment(self):
        with workspace() as ws:
            admin, _, _, _ = make(ws)
            items = {i.key: i for i in admin.checklist()}
            self.assertEqual(items['repos'].state, 'ok')
            self.assertNotIn('restart', items)
            admin.remove_repository('fixture', 'repo')
            items = {i.key: i for i in admin.checklist()}
            self.assertEqual(items['repos'].state, 'todo')
            self.assertEqual(items['restart'].state, 'warn')


if __name__ == '__main__':
    unittest.main()
