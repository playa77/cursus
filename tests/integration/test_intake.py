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
