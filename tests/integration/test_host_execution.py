"""Connected controller/Git/CLI lifecycle on the host runtime (ADR 0016).

Fixture CLIs run as the test user. This establishes admission, cleanup and
journal behavior only: no real CLI, login, provider call or isolation claim.
"""
import asyncio
from pathlib import Path
import unittest
from tests.phase_support import LANES, phase_runtime, phase_state
from tests.integration.test_execution import CAPACITY


class ConnectedHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_review_publication_with_host_lifecycle(self):
        async with phase_runtime() as rt:
            runner, runtime = rt['runner'], rt['execution'].runtime
            for _ in range(30):
                phase = await phase_state(rt)
                if phase['state'] in ('delivered', 'parked'):
                    break
                for lane in CAPACITY:
                    claim = await runner.claim(lane)
                    if claim:
                        await runner.dispatch(claim)
            self.assertEqual(phase['state'], 'delivered', phase.get('reason'))
            self.assertFalse(runtime.entries)
            self.assertEqual(len(rt['remote'].prs), 1)
            self.assertFalse(any(r['kind'] in ('grant', 'launch', 'event') for r in rt['journal'].records))
            for _ in range(4):
                await runner.cleanup_storage()
            self.assertFalse(runner.storage_pending())
            self.assertFalse(list((runtime.temporary).iterdir()))  # Per-attempt TMPDIRs are gone.


from contextlib import asynccontextmanager
from unittest.mock import patch
from tests.integration import test_debug


class HostDebugTests(test_debug.DebugTests):
    async def scenario(self, **kwargs):
        @asynccontextmanager
        async def saturated_runtime(*args, **options):
            async with phase_runtime(*args, **options) as rt:
                # Saturate part of the worker lane around the continuing debug session.
                from uuid import uuid4
                reservations = [str(uuid4()), str(uuid4())]
                for attempt in reservations:
                    self.assertTrue(await rt['execution'].runtime.reserve(attempt, 'worker', 'pi'))
                yield rt
                for attempt in reservations:
                    await rt['execution'].runtime.cleanup(attempt)
                self.assertFalse(rt['execution'].runtime.entries)
        with patch.object(test_debug, 'phase_runtime', saturated_runtime):
            await super().scenario(**kwargs)


class ProviderCeilingTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_frontier_can_hold_two_claims_without_shared_ceiling(self):
        from copy import deepcopy
        from uuid import uuid4
        from tests.support import code_input
        from tests.integration.test_execution import invocation
        async with phase_runtime() as rt:
            # The initial phase also belongs to Claude; use it as that lane's first.
            for cli, count in (('claude', 1), ('codex', 2), ('agy', 2)):
                for _ in range(count):
                    role = deepcopy(invocation(rt['execution'], cli, 'planner')['role'])
                    role['prompt_text'] = 'Fixture planner.'
                    rt['config']['roles']['planner'] = role
                    await rt['control'].action('local_operator', str(uuid4()), dict(kind='submit', input=code_input()))
            for _ in range(6):
                claim = await rt['runner'].claim('repository')
                self.assertIsNotNone(claim)
                await rt['runner'].dispatch(claim)
            held = []
            for cli in ('claude', 'codex', 'agy'):
                claims = [await rt['runner'].claim(cli), await rt['runner'].claim(cli)]
                self.assertTrue(all(claims))
                self.assertIsNone(await rt['runner'].claim(cli))
                held += claims
            self.assertEqual(len({c['attempt_id'] for c in held}), 6)


class PendingClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_started_claim_resumes_when_capacity_returns_without_reconnect(self):
        from uuid import uuid4
        from tests.phase_support import drive
        async with phase_runtime() as rt:
            await drive(rt, lambda p: p['state'] == 'execution')
            claim = await rt['runner'].claim('worker')
            runner, runtime = rt['runner'], rt['execution'].runtime
            holders = [str(uuid4()) for _ in range(CAPACITY['worker'])]
            for attempt in holders:
                self.assertTrue(await runtime.reserve(attempt, 'worker', 'pi'))
            self.assertIsNone(await runner.dispatch(claim))
            self.assertIn(claim['attempt_id'], runner.pending_claims)
            self.assertFalse(any(r['kind'] == 'launch' and r['value'] == claim['attempt_id'] for r in rt['journal'].records))
            self.assertTrue(await runtime.cleanup(holders[0]))
            task = asyncio.create_task(runner.serve())
            try:
                async with asyncio.timeout(25):
                    while (phase := await phase_state(rt))['state'] not in ('delivered', 'parked'):
                        if task.done():
                            await task
                        await asyncio.sleep(.05)
                self.assertEqual(phase['state'], 'delivered', phase.get('reason'))
                produced = [a for a in (await rt['db'].store.read('attempts'))['items'] if a['claim']['job']['step'] == 'produce']
                self.assertEqual([a['id'] for a in produced], [claim['attempt_id']])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                for attempt in holders:
                    await runtime.cleanup(attempt)


class SessionContainmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_peer_does_not_interrupt_additional_coding_role(self):
        from uuid import uuid4
        from tests.support import workspace
        from tests.integration.test_execution import fixture_execution, invocation, run
        from cursus.contracts import Problem
        with workspace() as first, workspace() as second:
            good, bad = fixture_execution(first), fixture_execution(second)
            bad.runtime = good.runtime = good.runtime  # One shared runtime, as in production.
            binary = Path(bad.clis['pi'])
            binary.write_text('#!/usr/bin/python3\nprint("[]",flush=True)\n')
            invocation_good = invocation(good, 'pi', 'worker')
            invocation_good['role']['name'] = 'artisan'
            jobs = [dict(step='produce', invocation=invocation_good), dict(step='produce', invocation=invocation(bad, 'pi', 'worker'))]
            results = await asyncio.gather(run(good, jobs[0], first.worktrees), run(bad, jobs[1], second.worktrees),
                                           return_exceptions=True)
            self.assertEqual(results[0]['summary'], 'Wrote result.txt')
            self.assertIsInstance(results[1], Problem)
            self.assertFalse(good.runtime.entries)
            self.assertTrue(all(p.returncode is not None for ps in good.runtime.children.values() for p in ps) or not good.runtime.children)


class DeploymentDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_is_durable_idempotent_and_stops_new_claims(self):
        from uuid import uuid4
        async with phase_runtime() as rt:
            key = str(uuid4())
            action = dict(kind='set_drain', enabled=True)
            first = await rt['control'].action('local_operator', key, action)
            self.assertEqual(first, await rt['control'].action('local_operator', key, action))
            self.assertIsNone(await rt['runner'].claim('repository'))
            status = await rt['control'].query('local_operator', 'deployment')
            self.assertEqual(status, dict(drain=True, unresolved_attempts=0, queued_jobs=1))
            remote = await rt['runner'].exchange('runners/' + rt['runner'].id + '/deployment', {})
            self.assertEqual(remote, status)
            await rt['control'].action('local_operator', str(uuid4()), dict(kind='set_drain', enabled=False))
            claim = await rt['runner'].claim('repository')
            self.assertIsNotNone(claim)
            self.assertEqual((await rt['control'].query('local_operator', 'deployment'))['unresolved_attempts'], 1)
