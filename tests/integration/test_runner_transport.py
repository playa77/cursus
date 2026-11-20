"""The in-process runner/control exchange keeps the idempotent, sequence-checked protocol (ADR 0016)."""
import unittest
from uuid import uuid4
from cursus.control import Control
from cursus.contracts import Problem
from cursus.runner import Journal, LocalTransport, Runner
from tests.integration.test_execution import fixture_execution
from tests.support import Database, SocketService, workspace, settings, code_input


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
                    runner = Runner(config['runner']['id'], journal,
                                    LocalTransport(control, config['runner']['id'], journal.generation),
                                    execution=fixture_execution(ws))
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

    async def test_control_problem_codes_reach_the_runner_and_foreign_runners_are_refused(self):
        async with Database() as db:
            config = settings()
            control = Control(config, db.store)
            generation = str(uuid4())
            mine = LocalTransport(control, config['runner']['id'], generation)
            with self.assertRaises(Problem) as claim_first:
                await mine.exchange('jobs/next', {'slot': 'repository'}, str(uuid4()), 'GET')
            self.assertEqual(claim_first.exception.code, 'state_conflict')  # Reconcile first.
            foreign = LocalTransport(control, str(uuid4()), generation)
            with self.assertRaises(Problem) as caught:
                await foreign.exchange('jobs/next', {'slot': 'repository'}, str(uuid4()), 'GET')
            self.assertEqual(caught.exception.code, 'forbidden')
            with self.assertRaises(Problem):
                await mine.exchange('jobs/next', {'slot': 'frontier'}, str(uuid4()), 'GET')  # No such lane.

    async def test_values_must_be_strict_json_as_on_the_old_wire(self):
        async with Database() as db:
            config = settings()
            transport = LocalTransport(Control(config, db.store), config['runner']['id'], str(uuid4()))
            for bad in ({'slot': {1, 2}}, {'slot': float('nan')}):
                with self.assertRaises((Problem, TypeError, ValueError)):
                    await transport.exchange('jobs/next', bad, str(uuid4()), 'GET')
