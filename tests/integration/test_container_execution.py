"""Connected controller/Git/CLI lifecycle using an explicit runtime surrogate.

Native fixture processes run on the test UID: this does not qualify namespaces,
UID separation, Podman resource enforcement or native-provider authentication.
"""
import asyncio
from pathlib import Path
import unittest
from cursus.containers import Containers
from cursus.runner import Runner
from tests.phase_support import phase_runtime, phase_state
from tests.unit.test_containers import RuntimeFixture, policy


class ProcessRuntime(Containers):
    async def spawn(self, argv, workspace, **kwargs):
        return await asyncio.create_subprocess_exec(*argv, cwd=workspace,
            env={'HOME':str(workspace), 'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}, **kwargs)


class ConnectedContainerTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_review_publication_with_container_lifecycle(self):
        async with phase_runtime() as rt:
            fixture = RuntimeFixture()
            settings, ceilings = policy(rt['ws'].root)
            runtime = ProcessRuntime(settings, rt['ws'].state/'runtime', ceilings, fixture)
            rt['execution'].runtime = runtime
            rt['config']['capacity'] = ceilings
            rt['repository'].container_workspaces = True
            runner = Runner(rt['runner'].id, rt['journal'], rt['runner'].transport,rt['repository'],rt['execution'])
            await runner.reconcile()
            for _ in range(30):
                phase = await phase_state(rt)
                if phase['state'] in ('delivered','parked'):
                    break
                for lane in ceilings:
                    claim = await runner.claim(lane)
                    if claim:
                        await runner.dispatch(claim)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertFalse(runtime.entries)
            self.assertEqual(len(rt['remote'].prs),1)
            self.assertTrue(any(c[0]=='create' and '--network=none' in c for c in fixture.calls))
            self.assertGreaterEqual(len([c for c in fixture.calls if c[0]=='rm']),5)
            self.assertFalse(any(r['kind'] in ('grant','launch','event') for r in rt['journal'].records))
            for _ in range(4):
                await runner.cleanup_storage()
            self.assertFalse(runner.storage_pending())


from contextlib import asynccontextmanager
from unittest.mock import patch
from tests.integration import test_debug


class ContainerDebugTests(test_debug.DebugTests):
    async def scenario(self, **kwargs):
        @asynccontextmanager
        async def container_runtime(*args, **options):
            async with phase_runtime(*args, **options) as rt:
                fixture = RuntimeFixture()
                settings, ceilings = policy(rt['ws'].root)
                rt['execution'].runtime = ProcessRuntime(settings,rt['ws'].state/'runtime',ceilings,fixture)
                # Saturate the non-verifier budget around the continuing debug session.
                from uuid import uuid4
                reservations = [str(uuid4()),str(uuid4())]
                for attempt in reservations:
                    self.assertTrue(await rt['execution'].runtime.reserve(attempt,'worker','pi'))
                rt['repository'].container_workspaces = True
                rt['runner'] = Runner(rt['runner'].id,rt['journal'],rt['runner'].transport,rt['repository'],rt['execution'])
                await rt['runner'].reconcile()
                yield rt
                for attempt in reservations:
                    await rt['execution'].runtime.cleanup(attempt)
                self.assertFalse(rt['execution'].runtime.entries)
        with patch.object(test_debug,'phase_runtime',container_runtime):
            await super().scenario(**kwargs)


class ProviderCeilingTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_frontier_can_hold_two_claims_without_shared_ceiling(self):
        from copy import deepcopy
        from uuid import uuid4
        from tests.support import code_input
        from tests.integration.test_execution import invocation
        async with phase_runtime() as rt:
            _, ceilings = policy(rt['ws'].root)
            rt['config']['capacity'] = ceilings
            # The initial phase also belongs to Claude; use it as that lane's first.
            for cli, count in (('claude',1),('codex',2),('agy',2)):
                for _ in range(count):
                    role = deepcopy(invocation(rt['execution'],cli,'planner')['role'])
                    role['prompt_text'] = 'Fixture planner.'
                    rt['config']['roles']['planner'] = role
                    await rt['control'].action('local_operator',str(uuid4()),dict(kind='submit',input=code_input()))
            for _ in range(6):
                claim = await rt['runner'].claim('repository')
                self.assertIsNotNone(claim)
                await rt['runner'].dispatch(claim)
            held = []
            for cli in ('claude','codex','agy'):
                claims = [await rt['runner'].claim(cli),await rt['runner'].claim(cli)]
                self.assertTrue(all(claims))
                self.assertIsNone(await rt['runner'].claim(cli))
                held += claims
            self.assertEqual(len({c['attempt_id'] for c in held}),6)

class PendingClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_started_claim_resumes_when_capacity_returns_without_reconnect(self):
        from uuid import uuid4
        from tests.phase_support import drive
        async with phase_runtime() as rt:
            await drive(rt,lambda p:p['state']=='execution')
            claim = await rt['runner'].claim('worker')
            fixture = RuntimeFixture()
            settings, ceilings = policy(rt['ws'].root)
            runtime = ProcessRuntime(settings,rt['ws'].state/'runtime',ceilings,fixture)
            rt['execution'].runtime = runtime
            rt['config']['capacity'] = ceilings
            rt['repository'].container_workspaces = True
            runner = Runner(rt['runner'].id,rt['journal'],rt['runner'].transport,rt['repository'],rt['execution'])
            await runner.reconcile()
            holders = [str(uuid4()) for _ in range(ceilings['worker'])]
            for attempt in holders:
                self.assertTrue(await runtime.reserve(attempt,'worker','pi'))
            self.assertIsNone(await runner.dispatch(claim))
            self.assertIn(claim['attempt_id'],runner.pending_claims)
            self.assertFalse(any(r['kind']=='launch' and r['value']==claim['attempt_id'] for r in rt['journal'].records))
            self.assertTrue(await runtime.cleanup(holders[0]))
            task = asyncio.create_task(runner.serve())
            try:
                async with asyncio.timeout(25):
                    while (phase := await phase_state(rt))['state'] not in ('delivered','parked'):
                        if task.done():
                            await task
                        await asyncio.sleep(.05)
                self.assertEqual(phase['state'],'delivered',phase.get('reason'))
                produced = [a for a in (await rt['db'].store.read('attempts'))['items'] if a['claim']['job']['step']=='produce']
                self.assertEqual([a['id'] for a in produced],[claim['attempt_id']])
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                for attempt in holders:
                    await runtime.cleanup(attempt)

class SessionContainmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_peer_does_not_interrupt_additional_coding_role(self):
        from uuid import uuid4
        from tests.support import workspace
        from tests.integration.test_execution import fixture_execution, invocation
        from cursus.contracts import Problem
        with workspace() as first, workspace() as second:
            fixture = RuntimeFixture()
            settings, ceilings = policy(first.root)
            runtime = ProcessRuntime(settings,first.state/'runtime',ceilings,fixture)
            good, bad = fixture_execution(first),fixture_execution(second)
            good.runtime = bad.runtime = runtime
            binary = Path(bad.profiles['pi']['binary'])
            binary.write_text('#!/usr/bin/python3\nprint("[]",flush=True)\n')
            good.profiles['pi']['qualified_roles'].append('artisan')
            invocation_good = invocation(good,'pi','worker')
            invocation_good['role']['name'] = 'artisan'
            jobs = [dict(step='produce',invocation=invocation_good),dict(step='produce',invocation=invocation(bad,'pi','worker'))]
            attempts = [str(uuid4()),str(uuid4())]
            for attempt in attempts:
                self.assertTrue(await runtime.reserve(attempt,'worker','pi'))
            results = await asyncio.gather(good.run(jobs[0],first.worktrees,attempts[0]),bad.run(jobs[1],second.worktrees,attempts[1]),return_exceptions=True)
            self.assertEqual(results[0]['summary'],'Wrote result.txt')
            self.assertIsInstance(results[1],Problem)
            self.assertFalse(runtime.entries)
            self.assertTrue(all(p.returncode is not None for p in fixture.processes.values()))

class DeploymentDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_is_durable_idempotent_and_stops_new_claims(self):
        from uuid import uuid4
        async with phase_runtime() as rt:
            key = str(uuid4())
            action = dict(kind='set_drain',enabled=True)
            first = await rt['control'].action('local_operator',key,action)
            self.assertEqual(first,await rt['control'].action('local_operator',key,action))
            self.assertIsNone(await rt['runner'].claim('repository'))
            status = await rt['control'].query('local_operator','deployment')
            self.assertEqual(status,dict(drain=True,unresolved_attempts=0,queued_jobs=1))
            remote = await rt['runner'].exchange('runners/'+rt['runner'].id+'/deployment',{})
            self.assertEqual(remote,status)
            await rt['control'].action('local_operator',str(uuid4()),dict(kind='set_drain',enabled=False))
            claim = await rt['runner'].claim('repository')
            self.assertIsNotNone(claim)
            self.assertEqual((await rt['control'].query('local_operator','deployment'))['unresolved_attempts'],1)
