import asyncio
import unittest
from uuid import uuid4
from cursus.control import Control
from cursus.contracts import Problem
from cursus.http import request_local
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
                self.assertEqual(len((await db.store.read('phases'))['items']), 1)

    async def test_submission_is_refused_while_any_role_is_unqualified_and_allowed_after(self):
        async with Database() as db:
            config = settings()
            config['unqualified_roles'] = ['planner']
            control = Control(config, db.store)
            with workspace() as ws:
                async with SocketService(control, ws.root / 'operator.sock'):
                    async def submit():
                        return await asyncio.to_thread(request_local, str(ws.root / 'operator.sock'),
                                                       '/operator/actions', {'kind': 'submit', 'input': code_input()}, str(uuid4()))
                    with self.assertRaises(Problem) as caught:
                        await submit()
                    self.assertEqual(caught.exception.code, 'roles_unqualified')
                    self.assertIn('planner', caught.exception.message)
                    self.assertNotIn('worker', caught.exception.message)
                    self.assertEqual((await db.store.read('phases'))['items'], [])
                    config['unqualified_roles'] = []
                    await submit()
