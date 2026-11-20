"""One process runs the control plane, the runner and both HTTP surfaces (ADR 0016).

Fixture CLIs and a fixture Git remote; real PostgreSQL schema, real operator socket,
real journal and host runtime. No real CLI, login or GitHub is involved.
"""
import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from cursus.bootstrap import check_identity, run
from cursus.config import load
from cursus.contracts import Problem
from cursus.http import request_local
from tests.integration.test_execution import fixture_execution
from tests.support import Database, code_input, serve_config, workspace


class ServeTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_process_delivers_a_phase_and_stops_cleanly(self):
        async with Database() as db:
            with workspace() as ws:
                dsn = os.environ['CURSUS_TEST_DSN']
                dsn += ('&' if '?' in dsn else '?') + 'search_path=' + db.schema
                clis = fixture_execution(ws).clis
                path, _, _, remote = serve_config(ws, dsn, clis=clis)
                (remote.seed / 'result.txt').write_text('done')
                remote.git(remote.seed, 'add', '.')
                remote.git(remote.seed, 'commit', '-m', 'Passing baseline')
                remote.git(remote.seed, 'push', 'origin', 'main')
                settings = load('serve', str(path))
                settings['repositories'][0]['remote'] = str(remote.remote)  # Fixture-only; not loadable from TOML.
                socket = ws.root / 'operator.sock'
                task = asyncio.create_task(run(settings, github=remote))
                try:
                    for _ in range(200):
                        if socket.exists() or task.done():
                            break
                        await asyncio.sleep(.05)
                    if task.done():
                        await task
                    reply = await asyncio.to_thread(request_local, str(socket), '/operator/actions',
                                                    {'kind': 'submit', 'input': code_input()}, str(uuid4()))
                    phase_id = reply['entity_id']
                    async with asyncio.timeout(90):
                        while True:
                            phase = (await asyncio.to_thread(request_local, str(socket), '/phases/' + phase_id))['items'][0]
                            if phase['state'] in ('delivered', 'parked'):
                                break
                            if task.done():
                                await task
                            await asyncio.sleep(.2)
                    self.assertEqual(phase['state'], 'delivered', phase.get('reason'))
                    self.assertEqual(len(remote.prs), 1)
                    deployment = await asyncio.to_thread(request_local, str(socket), '/deployment')
                    self.assertEqual(deployment['unresolved_attempts'], 0)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.assertFalse(socket.exists())  # The operator socket is removed on stop.
                self.assertFalse(list((ws.state / 'execution' / 'tmp').iterdir()))  # No leaked per-attempt TMPDIRs.

    async def test_any_component_ending_ends_the_process(self):
        async with Database() as db:
            with workspace() as ws:
                dsn = os.environ['CURSUS_TEST_DSN']
                dsn += ('&' if '?' in dsn else '?') + 'search_path=' + db.schema
                path, *_ = serve_config(ws, dsn)
                settings = load('serve', str(path))
                async def fails(*args, **kwargs):
                    raise Problem('supervision', 'Runner supervision stopped; intake closed.')
                with patch('cursus.runner.Runner.serve', fails):
                    with self.assertRaises(Problem):
                        async with asyncio.timeout(30):
                            await run(settings)
                self.assertFalse((ws.root / 'operator.sock').exists())


class IdentityTests(unittest.TestCase):
    def settings(self, user):
        return {'service': {'user': user}}

    def test_root_is_refused(self):
        with patch('os.geteuid', return_value=0):
            with self.assertRaises(Problem) as caught:
                check_identity(self.settings('root'))
        self.assertEqual(caught.exception.code, 'identity_boundary')

    def test_the_running_user_must_be_the_configured_user(self):
        import pwd
        other = next((u.pw_name for u in pwd.getpwall() if u.pw_uid != os.getuid()), None)
        self.assertIsNotNone(other)
        with patch('os.geteuid', return_value=1000):
            with self.assertRaises(Problem):
                check_identity(self.settings(other))
            check_identity(self.settings(pwd.getpwuid(os.getuid()).pw_name))


if __name__ == '__main__':
    unittest.main()
