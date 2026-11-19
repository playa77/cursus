import asyncio
import unittest
from uuid import uuid4
from cursus.control import Control
from cursus.contracts import Problem, canonical_json, decode_json
from cursus.http import LocalConnection
from cursus.runner import Journal, Runner
from tests.support import Database, SocketService, workspace, settings, code_input


class Wire:
    """External HTTP transport fixture, retaining the production auth/routes."""
    def __init__(self, socket, generation):
        self.socket, self.generation = str(socket), generation

    async def exchange(self, route, value, key, method='POST'):
        def send():
            from urllib.parse import urlencode
            connection = LocalConnection(self.socket)
            url = '/' + route + ('?' + urlencode(value) if method == 'GET' else '')
            try:
                connection.request(method, url, canonical_json(value) if method != 'GET' else None,
                    {'Authorization': 'Bearer fixture-bearer', 'X-Cursus-Generation': self.generation,
                     'Idempotency-Key': key, 'Content-Type': 'application/json'})
                response = connection.getresponse()
                if response.status == 204:
                    return None
                result = decode_json(response.read())
                if response.status >= 400:
                    raise Problem(**result)
                return result
            finally:
                connection.close()
        return await asyncio.to_thread(send)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_claim_replay_and_gap(self):
        async with Database() as db:
            config = settings()
            control = Control(config, db.store)
            with workspace() as ws:
                journal = Journal(ws.state)
                try:
                    with self.assertRaises(BlockingIOError):
                        Journal(ws.state)
                    async with SocketService(control, ws.root / 'runner.sock', False):
                        runner = Runner(config['runner']['id'], journal,
                                        Wire(ws.root / 'runner.sock', journal.generation))
                        await runner.reconcile()
                        self.assertIsNone(await runner.claim('repository'))
                        await control.action('local_operator', str(uuid4()), {'kind': 'submit', 'input': code_input()})
                        key = str(uuid4())
                        grant = await runner.claim('repository', key)
                        self.assertEqual(grant, await runner.claim('repository', key))
                        self.assertEqual(len((await db.store.read('attempts'))['items']), 1)
                        with self.assertRaises(Problem) as caught:
                            await runner.exchange(f"attempts/{grant['attempt_id']}/events", [{
                                'attempt_id': grant['attempt_id'], 'seq': 2, 'kind': 'started', 'payload': {'service_activation': str(uuid4()), 'time': '2026-11-19T00:00:00Z'}}])
                        self.assertEqual(caught.exception.code, 'sequence_conflict')
                        self.assertEqual((await db.store.read('attempts'))['items'][0]['ack'], 0)
                        event = {'attempt_id': grant['attempt_id'], 'seq': 1, 'kind': 'started',
                                 'payload': {'service_activation': str(uuid4()), 'time': '2026-11-19T00:00:00Z'}}
                        route = f"attempts/{grant['attempt_id']}/events"
                        ack = await runner.exchange(route, [event])
                        self.assertEqual(ack, await runner.exchange(route, [event]))
                        with self.assertRaises(Problem):
                            await runner.exchange(route, [dict(event, payload=dict(event['payload'], time='2026-11-19T00:00:01Z'))])
                        self.assertEqual(ack['committed_through'], 1)
                        self.assertEqual([r['kind'] for r in journal.records].count('grant'), 1)
                finally:
                    journal.close()
                reopened = Journal(ws.state)
                self.assertTrue(any(r['kind'] == 'grant' for r in reopened.records))
                reopened.close()
