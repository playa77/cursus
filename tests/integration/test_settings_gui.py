"""Settings and System pages through the real HTTP surface (ADR 0018).

Real PostgreSQL schema, real loader and files, real git for role releases, real CSRF/Origin/identity
checks with a fixture Serve boundary. No CLI, login or GitHub is involved.
"""
import asyncio
import os
import re
import subprocess
import tomllib
import unittest
from unittest.mock import patch
from uuid import uuid4
from cursus.admin import Admin
from cursus.browser import environment
from cursus.config import load
from cursus.control import Control
from tests.integration.test_browser import BrowserWire, LOGIN, ORIGIN
from tests.support import Database, SocketService, code_input, serve_config, workspace


class Gui:
    pass


class SettingsGuiTests(unittest.IsolatedAsyncioTestCase):
    async def start(self, qualified=True, supervised=False, with_admin=True):
        db = await Database().__aenter__()
        self.addAsyncCleanup(db.__aexit__, None, None, None)
        ws_context = workspace()
        ws = ws_context.__enter__()
        self.addCleanup(ws_context.__exit__, None, None, None)
        path, release, commit, _ = serve_config(ws, 'postgresql:///unused', qualified=qualified)
        settings = load('serve', str(path))
        settings['service'].update(external_origin=ORIGIN, operator_login=LOGIN)
        control = Control(settings, db.store)
        control.admin = Admin(settings, supervised=supervised) if with_admin else None
        socket = ws.root / 'browser.sock'
        service = await SocketService(control, socket, local=False, browser=True).__aenter__()
        self.addAsyncCleanup(service.__aexit__, None, None, None)
        g = Gui()
        g.db, g.ws, g.path, g.release, g.control, g.admin, g.wire = db, ws, path, release, control, control.admin, BrowserWire(socket)
        return g

    async def get(self, g, path, **kw):
        status, headers, raw = await g.wire.request(path, **kw)
        return status, headers, raw.decode()

    async def token(self, g):
        status, _, body = await self.get(g, '/settings/capacity')
        self.assertEqual(status, 200)
        return re.search(r'name="csrf" value="([^"]+)"', body)[1]

    async def post(self, g, path, data, **kw):
        data = dict(data, csrf=data.get('csrf') or await self.token(g))
        status, headers, raw = await g.wire.request(path, data, **kw)
        return status, headers, raw.decode()

    def on_disk(self, g):
        return tomllib.loads(g.path.read_text())

    # --- access and boundary --------------------------------------------------------------------

    async def test_every_page_renders_and_the_boundary_is_enforced(self):
        g = await self.start()
        pages = ['/settings', '/settings/access', '/settings/capacity', '/settings/resources', '/settings/limits',
                 '/settings/publisher', '/settings/repositories', '/settings/repositories/new',
                 '/settings/repositories/fixture/repo', '/settings/roles', '/settings/roles/planner',
                 '/settings/prompts/planner.md', '/settings/system', '/', '/?new=1', '/?attempts=1']
        for page in pages:
            status, _, body = await self.get(g, page)
            self.assertEqual(status, 200, page)
            self.assertIn('Settings &amp; system', body, page)
        for page in pages[:3]:
            for override in ({'Tailscale-User-Login': 'wrong'}, {'Host': 'evil.invalid'}):
                self.assertEqual((await g.wire.request(page, headers=override))[0], 403)
        for bad in ('/settings/nope', '/settings/repositories/fixture/missing', '/settings/roles/ghost',
                    '/settings/prompts/missing.md', '/settings/prompts/..%2Fx.md', '/settings/repositories/new/new'):
            self.assertIn((await g.wire.request(bad))[0], (404, 422), bad)

    async def test_pages_do_not_exist_without_an_admin_layer(self):
        g = await self.start(with_admin=False)
        self.assertEqual((await g.wire.request('/settings'))[0], 404)
        status, _, body = await self.get(g, '/')
        self.assertEqual(status, 200)
        self.assertNotIn('Settings &amp; system', body)

    async def test_writes_need_csrf_and_the_exact_origin(self):
        g = await self.start()
        token = await self.token(g)
        form = {'capacity.worker': '3', 'capacity.claude': '1', 'capacity.codex': '1', 'capacity.agy': '1'}
        before = g.path.read_bytes()
        self.assertEqual((await g.wire.request('/settings/capacity', dict(form, csrf='wrong')))[0], 403)
        self.assertEqual((await g.wire.request('/settings/capacity', form))[0], 403)
        self.assertEqual((await g.wire.request('/settings/capacity', dict(form, csrf=token), {'Origin': 'https://evil.invalid'}))[0], 403)
        self.assertEqual(g.path.read_bytes(), before)

    # --- sections -------------------------------------------------------------------------------

    async def test_saving_a_section_writes_the_file_and_flags_a_pending_restart_everywhere(self):
        g = await self.start()
        form = {'capacity.worker': '3', 'capacity.claude': '2', 'capacity.codex': '1', 'capacity.agy': '1'}
        status, headers, _ = await self.post(g, '/settings/capacity', form)
        self.assertEqual((status, headers['location']), (303, '/settings/capacity?saved=saved'))
        self.assertEqual(self.on_disk(g)['capacity']['worker'], 3)
        self.assertEqual(g.control.settings['capacity']['worker'], 2)      # running values are untouched
        for page in ('/', '/settings/capacity', '/settings'):
            self.assertIn('Saved settings are not running yet', (await self.get(g, page))[2], page)
        _, _, body = await self.get(g, '/settings/system')
        self.assertIn('capacity.worker', body)
        self.assertIn('changes pending', body)
        _, _, body = await self.get(g, '/settings/capacity?saved=saved')
        self.assertIn('Saved. Applies after a restart', body)

    async def test_rejected_values_rerender_the_form_with_input_and_messages(self):
        g = await self.start()
        before = g.path.read_bytes()
        status, _, body = await self.post(g, '/settings/capacity',
                                          {'capacity.worker': '9', 'capacity.claude': 'many', 'capacity.codex': '1', 'capacity.agy': '1'})
        self.assertEqual(status, 422)
        self.assertIn('pi workers: Must be between 1 and 4.', body)
        self.assertIn('Claude Code sessions: Enter a whole number.', body)
        self.assertIn('value="many"', body)            # the operator's input is kept
        self.assertEqual(g.path.read_bytes(), before)

    async def test_access_values_are_html_escaped_and_validated(self):
        g = await self.start()
        status, _, body = await self.post(g, '/settings/access', dict(g.admin.values('access'), **{
            'service.external_origin': '"><script>alert(1)</script>', 'service.listen_port': '8787'}))
        self.assertEqual(status, 422)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('&lt;script&gt;', body)

    # --- repositories ---------------------------------------------------------------------------

    def repository(self, **overrides):
        form = {'owner': 'acme', 'name': 'widgets', 'object_format': 'sha1', 'allowed_target_refs': 'refs/heads/main',
                'phase_check_ids': 'unit', 'check_rows': '2', 'check.0.id': 'unit',
                'check.0.argv': '/usr/bin/python3\n-m\nunittest', 'check.0.cwd': '.', 'check.0.timeout_seconds': '300',
                'check.1.id': '', 'check.1.argv': '', 'check.1.cwd': '.', 'check.1.timeout_seconds': '300'}
        form.update(overrides)
        return form

    async def test_enroll_edit_and_remove_a_repository(self):
        g = await self.start()
        status, headers, _ = await self.post(g, '/settings/repositories/new', self.repository())
        self.assertEqual((status, headers['location']), (303, '/settings/repositories/acme/widgets?saved=saved'))
        self.assertEqual(self.on_disk(g)['repositories'][1]['checks'][0]['argv'], ['/usr/bin/python3', '-m', 'unittest'])
        _, _, body = await self.get(g, '/settings/repositories')
        self.assertIn('acme/widgets', body)
        _, _, body = await self.get(g, '/settings/repositories/acme/widgets')
        self.assertIn('/usr/bin/python3\n-m\nunittest', body.replace('&#10;', '\n'))
        status, _, _ = await self.post(g, '/settings/repositories/acme/widgets', self.repository(allowed_target_refs='refs/heads/main\nrefs/heads/dev'))
        self.assertEqual(status, 303)
        self.assertEqual(self.on_disk(g)['repositories'][1]['allowed_target_refs'], ['refs/heads/main', 'refs/heads/dev'])
        status, _, body = await self.post(g, '/settings/repositories/new', self.repository(**{'check.0.argv': 'relative'}))
        self.assertEqual(status, 422)
        self.assertIn('first line must be an absolute path', body)
        status, headers, _ = await self.post(g, '/settings/repositories/acme/widgets/remove', {})
        self.assertEqual((status, headers['location']), (303, '/settings/repositories?saved=removed'))
        self.assertEqual(len(self.on_disk(g)['repositories']), 1)

    async def test_a_repository_with_unfinished_phases_cannot_be_removed(self):
        g = await self.start()
        await g.control.action('local_operator', str(uuid4()), {'kind': 'submit', 'input': code_input()})
        before = g.path.read_bytes()
        status, _, body = await self.post(g, '/settings/repositories/fixture/repo/remove', {})
        self.assertEqual(status, 422)
        self.assertIn('unfinished phase(s) still use this repository', body)
        self.assertEqual(g.path.read_bytes(), before)

    # --- roles and prompts ----------------------------------------------------------------------

    def role(self, **overrides):
        form = {'cli': 'claude', 'tier': 'organization', 'model': 'model-y', 'reasoning': 'high', 'provider': '',
                'timeout_seconds': '300', 'prompt': 'planner.md', 'tool.read': 'on', 'tool.list': 'on', 'tool.search': 'on'}
        form.update(overrides)
        return form

    def git(self, g, *args):
        return subprocess.run(['git', '-C', str(g.release), *args], capture_output=True, text=True, check=True).stdout.strip()

    async def test_role_save_commits_pins_and_reports_the_release(self):
        g = await self.start(qualified=False)
        status, _, body = await self.get(g, '/settings/roles')
        self.assertIn('needs model, reasoning', body)
        self.assertIn('needs reasoning, provider', body)       # worker: the model is already chosen
        status, headers, _ = await self.post(g, '/settings/roles/planner', self.role())
        self.assertEqual(status, 303)
        commit = self.git(g, 'rev-parse', 'HEAD')
        self.assertEqual(headers['location'], f'/settings/roles?saved={commit[:10]}')
        self.assertEqual(self.on_disk(g)['service']['role_release_commit'], commit)
        _, _, body = await self.get(g, headers['location'])
        self.assertIn(f'Role release {commit[:10]} committed and pinned', body)
        self.assertIn('model-y', body)
        status, _, body = await self.post(g, '/settings/roles/planner', self.role(model='-bad', **{'tool.bash': 'on'}))
        self.assertEqual(status, 422)
        self.assertIn('value="-bad"', body)
        self.assertEqual(self.git(g, 'rev-parse', 'HEAD'), commit)

    async def test_prompt_save_and_the_pin_action(self):
        g = await self.start()
        status, headers, _ = await self.post(g, '/settings/prompts/judge.md', {'text': 'Edited judge prompt.\n'})
        self.assertEqual(status, 303)
        self.assertEqual(load('serve', str(g.path))['roles']['judge']['prompt_text'], 'Edited judge prompt.\n')
        status, _, body = await self.post(g, '/settings/prompts/judge.md', {'text': '   '})
        self.assertEqual(status, 422)
        (g.release / 'prompts' / 'scout.md').write_text('Hand edit.\n')
        _, _, body = await self.get(g, '/settings/roles')
        self.assertIn('differ', body)
        status, _, _ = await self.post(g, '/settings/roles/pin', {})
        self.assertEqual(status, 303)
        self.assertFalse(g.admin.release_state()['dirty'])

    # --- publisher token ------------------------------------------------------------------------

    async def test_the_token_is_stored_privately_and_never_rendered_or_echoed(self):
        g = await self.start()
        secret = 'ghp_SuperSecretTokenValue123'
        status, headers, body = await self.post(g, '/settings/publisher/token', {'token': secret})
        self.assertEqual((status, headers['location']), (303, '/settings/publisher?saved=token'))
        self.assertNotIn(secret, body + str(headers))
        _, _, body = await self.get(g, headers['location'])
        self.assertNotIn(secret, body)
        self.assertIn('stored', body)
        bad = 'has spaces and @ symbols'
        status, _, body = await self.post(g, '/settings/publisher/token', {'token': bad})
        self.assertEqual(status, 422)
        self.assertNotIn(bad, body)
        from pathlib import Path
        self.assertEqual(Path(g.admin.read_raw()['publisher']['github_credential_file']).read_text(), secret + '\n')

    # --- system: drain, restart, preflight, history ---------------------------------------------

    async def test_drain_and_reopen_from_the_website(self):
        g = await self.start()
        token = await self.token(g)
        for enabled, word in (('true', 'drained'), ('false', 'open')):
            status, headers, _ = await g.wire.request('/operator/actions',
                {'kind': 'set_drain', 'enabled': enabled, 'csrf': token, 'request_id': str(uuid4())})
            self.assertEqual((status, headers['location']), (303, '/settings/system?saved=1'))
            self.assertEqual((await g.db.store.deployment())['drain'], enabled == 'true')
            self.assertIn(f'>{word}<', (await self.get(g, '/settings/system'))[2])
        status, _, _ = await g.wire.request('/operator/actions', {'kind': 'set_drain', 'enabled': 'maybe', 'csrf': token, 'request_id': str(uuid4())})
        self.assertEqual(status, 422)

    async def test_restart_is_refused_unsupervised_or_busy_and_honored_when_idle_or_forced(self):
        g = await self.start(supervised=False)
        status, _, body = await self.post(g, '/settings/system/restart', {})
        self.assertEqual(status, 422)
        self.assertIn('not running under systemd', body)
        g.admin.supervised = True
        await g.control.action('local_operator', str(uuid4()), {'kind': 'submit', 'input': code_input()})
        status, _, body = await self.post(g, '/settings/system/restart', {})
        self.assertEqual(status, 422)
        self.assertIn('cannot resume a running CLI session', body)
        self.assertFalse(g.admin.restart_requested)
        status, _, body = await self.post(g, '/settings/system/restart', {'interrupt': 'on'})
        self.assertEqual(status, 200)
        self.assertIn('Restarting Cursus', body)
        self.assertTrue(g.admin.restart_requested)

    async def test_idle_restart_needs_no_confirmation_flag(self):
        g = await self.start(supervised=True)
        status, _, body = await self.post(g, '/settings/system/restart', {})
        self.assertEqual(status, 200)
        self.assertTrue(g.admin.restart_requested)

    async def test_preflight_runs_from_the_website_and_reports_missing_clis(self):
        g = await self.start()
        with patch('cursus.recipes.resolve', return_value=None):
            status, headers, _ = await self.post(g, '/settings/system/preflight', {})
        self.assertEqual((status, headers['location']), (303, '/settings/system?saved=preflight'))
        _, _, body = await self.get(g, '/settings/system')
        for cli in ('claude', 'codex', 'agy', 'pi'):
            self.assertIn(f'<td>{cli}</td>', body)
        self.assertIn('Not found', body)
        self.assertIn('cannot tell whether a CLI is signed in', body)

    async def test_history_and_restore(self):
        g = await self.start()
        original = self.on_disk(g)['capacity']['worker']
        await self.post(g, '/settings/capacity', {'capacity.worker': '4', 'capacity.claude': '1', 'capacity.codex': '1', 'capacity.agy': '1'})
        _, _, body = await self.get(g, '/settings/system')
        name = re.search(r'name="name" value="(cursus-[^"]+\.toml)"', body)[1]
        status, headers, _ = await self.post(g, '/settings/system/restore', {'name': name})
        self.assertEqual((status, headers['location']), (303, '/settings/system?saved=restored'))
        self.assertEqual(self.on_disk(g)['capacity']['worker'], original)
        status, _, _ = await self.post(g, '/settings/system/restore', {'name': '../../etc/passwd'})
        self.assertEqual(status, 422)

    # --- overview and intake --------------------------------------------------------------------

    async def test_overview_guides_setup_and_intake_has_no_dead_ends(self):
        g = await self.start(qualified=False)
        _, _, body = await self.get(g, '/')
        self.assertIn('Finish setting up', body)
        self.assertIn('Choose a model, reasoning level and provider for', body)
        self.assertIn('Intake: ', body)
        g.control.settings['unqualified_roles'] = ['planner']
        _, _, body = await self.get(g, '/?new=1')
        self.assertIn('still need a model and reasoning level', body)
        g.control.settings['repositories'] = []
        _, _, body = await self.get(g, '/?new=1')
        self.assertIn('/settings/repositories/new', body)

    async def test_agent_output_panels_render_every_shape_without_error(self):
        phase = dict(id=str(uuid4()), state='intake', revision=3, spec='Final <b>spec</b>', spec_revision=2,
                     input=dict(workflow='code', source=dict(kind='interview'), repo=dict(owner='o', name='n', target_ref='refs/heads/main')),
                     interviews=[{'result': {'kind': 'questions', 'questions': [{'text': 'Why?', 'required': True}]}},
                                 {'question': {'text': 'Why?', 'answer': 'Because <i>reasons</i>'}, 'spec_revision': 1},
                                 {'result': {'kind': 'complete', 'text': 'x'}}],
                     debate=dict(mode='spec', judgment=dict(verdict='accept'), blocking=False),
                     debate_history=[{'role': 'critic', 'result': {'objections': [{'id': 'o1', 'severity': 'major', 'evidence': 'e', 'fix': 'f'}]}},
                                     {'role': 'judge', 'result': {'rulings': [{'id': 'o1', 'upheld': True, 'rationale': 'r'}],
                                                                  'required_amendments': ['a'], 'questions': [], 'verdict': 'accept'}}],
                     plan=dict(packages=[dict(id='p1', objective='Do it', criteria=[dict(id='c1')])]),
                     repair_findings=['finding one'], repair_count=2, integration_review=dict(verdict='accept', findings=[]))
        html = environment().get_template('details.html').render(phase=phase, record=phase)
        for text in ('Interview transcript', 'Because &lt;i&gt;reasons&lt;/i&gt;', 'Final &lt;b&gt;spec&lt;/b&gt;', 'critic', 'upheld',
                     'Latest verdict', 'p1', '2 repair round(s)', 'Complete phase record'):
            self.assertIn(text, html)
        self.assertNotIn('<b>spec</b>', html)
        self.assertNotIn('<i>reasons</i>', html)


if __name__ == '__main__':
    unittest.main()
