import asyncio
import unittest
from uuid import uuid4
from pathlib import Path
from cursus.control import Control
from cursus.contracts import Problem
from cursus.http import request_local, LocalConnection
from tests.support import Database, SocketService, workspace, settings, code_input


class IntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_submit_replay_and_denials(self):
        async with Database() as db:
            control = Control(settings(), db.store)
            with workspace() as ws:
                async with SocketService(control, ws.root / 'operator.sock'):
                    key = str(uuid4())
                    async def submit(value, request=key):
                        return await asyncio.to_thread(request_local, str(ws.root / 'operator.sock'),
                                                       '/operator/actions', value, request)
                    action = {'kind': 'submit', 'input': code_input()}
                    reply = await submit(action)
                    self.assertEqual(reply, await submit(action))
                    self.assertEqual(len((await db.store.read('jobs'))['items']), 1)
                    changed = {'kind': 'submit', 'input': dict(code_input(), plan_debate=True)}
                    with self.assertRaises(Problem):
                        await submit(changed)
                    with self.assertRaises(Problem):
                        await submit(changed, str(uuid4()))
                    self.assertEqual(len((await db.store.read('phases'))['items']), 1)
                async with SocketService(control, ws.root / 'runner.sock', local=False):
                    with self.assertRaises(Problem) as caught:
                        await asyncio.to_thread(request_local, str(ws.root / 'runner.sock'),
                                                '/operator/actions', action, str(uuid4()))
                    self.assertEqual(caught.exception.code, 'unauthorized')
                self.assertEqual(len((await db.store.read('phases'))['items']), 1)

    async def test_control_process_bootstrap_socket_lifetime(self):
        import json
        import os
        import sys
        from tests.support import control_config
        async with Database() as db:
            with workspace() as ws:
                dsn = os.environ['CURSUS_TEST_DSN']
                dsn += ('&' if '?' in dsn else '?') + 'search_path=' + db.schema
                config = control_config(ws, dsn)
                process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'cursus.bootstrap',
                    'control', '--config', str(config), env={'PATH':'/usr/bin:/bin',
                    'PYTHONPATH':str(Path('src').resolve())},
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    for _ in range(100):
                        if (ws.root/'operator.sock').exists() or process.returncode is not None:
                            break
                        await asyncio.sleep(.05)
                    reply = await asyncio.to_thread(request_local, str(ws.root/'operator.sock'),
                        '/operator/actions', {'kind':'submit','input':code_input()}, str(uuid4()))
                    self.assertEqual(reply['state'], 'intake')
                    self.assertEqual(len((await db.store.read('phases'))['items']), 1)
                finally:
                    if process.returncode is None:
                        process.terminate()
                    try:
                        stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
                    except TimeoutError:
                        process.kill()
                        await process.communicate()
                        self.fail('Control did not stop both listeners on SIGTERM.')
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertFalse((ws.root/'operator.sock').exists())
