"""Lifecycle fixtures, not Podman/namespace/provider qualification."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from uuid import uuid4
from cursus.containers import Containers
from cursus.config import capacity, container_settings
from cursus.contracts import Problem
from tests.support import workspace


def policy(root, workers=4):
    ceilings = dict(worker=workers, claude=2, codex=2, agy=2, verifier=1, repository=1)
    resource = dict(memory_mb=1000, cpu_millis=500, pids=32, tmp_mb=64, home_mb=64)
    credentials = {}
    for cli in ('pi','claude','codex','agy'):
        credentials[cli] = []
        for i in range(workers if cli == 'pi' else 2):
            path = root / ('auth-' + cli + str(i))
            path.mkdir(mode=0o700, exist_ok=True)
            credentials[cli].append(dict(id=cli+str(i), evidence='fixture-only',
                mounts=[dict(source=str(path), target='/home/session/auth')]))
    return dict(binary='/usr/bin/podman', version='5.0.0', image='sha256:'+'a'*64,
        network='private', disk_reserve_mb=1, resources=dict(agent=resource, verifier=resource),
        budget=dict(memory_mb=4000, cpu_millis=5000, pids=256, host_reserve_mb=1024,
                    host_reserve_cpu_millis=1000), credentials=credentials), ceilings


class RuntimeFixture:
    """Keeps a real process alive during unavailable-runtime observations."""
    def __init__(self):
        self.objects, self.calls, self.failures = {}, [], set()
        self.process = None
        self.processes = {}

    async def __call__(self, *args):
        self.calls.append(args)
        action = args[1] if args[0] == 'container' else args[0]
        if action in self.failures:
            return 125, b''
        if action == 'exists':
            return (0 if args[-1] in self.objects else 1), b''
        if action == 'inspect':
            return 0, json.dumps([self.objects[args[-1]]]).encode()
        if action == 'create':
            name = args[args.index('--name')+1]
            token = args[args.index('--label')+1].split('=',1)[1]
            self.objects[name] = dict(Id=__import__('hashlib').sha256(name.encode()).hexdigest(), Name=name, Image='a'*64, Config={'User':'1000:1000','Labels':{'io.cursus.owner':token}}, State={'Running':False})
            return 0, self.objects[name]['Id'].encode()
        value = next(v for v in self.objects.values() if v['Id']==args[-1])
        if action == 'start':
            self.process = await asyncio.create_subprocess_exec('/usr/bin/sleep', '60')
            self.processes[value['Id']] = self.process
            value['State']['Running'] = True
        if action == 'stop':
            process = self.processes.get(value['Id'])
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            value['State']['Running'] = False
        if action == 'rm':
            del self.objects[value['Name']]
        return 0, b''


class ContainerTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_boot_uncertainty_surviving_process_then_productivity(self):
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            fixture = RuntimeFixture()
            runtime = Containers(settings, ws.state, ceilings, fixture)
            attempt = str(uuid4())
            self.assertTrue(await runtime.reserve(attempt, 'worker', 'pi'))
            await runtime.prepare(attempt, ws.worktrees)
            process = fixture.process
            fixture.failures.add('exists')
            self.assertFalse(await runtime.cleanup(attempt))
            self.assertIsNone(process.returncode)  # Real execution remains.
            restarted = Containers(settings, ws.state, ceilings, fixture)
            self.assertEqual((await restarted.recover())[attempt], False)
            self.assertEqual(restarted.entries[attempt]['state'], 'uncertain')
            self.assertEqual(len([c for c in fixture.calls if c[0]=='start']), 1)
            fixture.failures.clear()
            self.assertEqual((await restarted.recover())[attempt], True)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(restarted.entries)
            self.assertTrue(await restarted.reserve(str(uuid4()), 'worker', 'pi'))

    async def test_identity_collision_never_stops_other_execution(self):
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            fixture = RuntimeFixture()
            runtime = Containers(settings, ws.state, ceilings, fixture)
            attempt = str(uuid4())
            await runtime.reserve(attempt, 'worker', 'pi')
            item = runtime.entries[attempt]
            fixture.objects[item['name']] = dict(Id='c'*64, Name=item['name'], Config={'Labels':{}}, State={'Running':True})
            self.assertFalse(await runtime.cleanup(attempt))
            self.assertFalse(any(c[0] in ('stop','rm') for c in fixture.calls))
            self.assertIn(attempt, runtime.entries)

    async def test_reserved_verifier_and_credential_exclusivity(self):
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            runtime = Containers(settings, ws.state, ceilings, RuntimeFixture())
            for _ in range(3):
                self.assertTrue(await runtime.reserve(str(uuid4()), 'worker', 'pi'))
            self.assertFalse(await runtime.reserve(str(uuid4()), 'worker', 'pi'))
            self.assertTrue(await runtime.reserve(str(uuid4()), 'verifier'))
            self.assertEqual(len({e['domain'] for e in runtime.entries.values() if e['cli']}), 3)
            self.assertFalse(runtime.fits('claude'))

    async def test_cleanup_retry_after_remove_failure_and_preparation_failure(self):
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            fixture = RuntimeFixture()
            runtime = Containers(settings, ws.state, ceilings, fixture)
            attempt = str(uuid4())
            await runtime.reserve(attempt, 'verifier')
            fixture.failures.add('create')
            with self.assertRaises(Problem):
                await runtime.prepare(attempt, ws.worktrees)
            self.assertTrue(await runtime.cleanup(attempt))
            fixture.failures.clear()
            attempt = str(uuid4())
            await runtime.reserve(attempt, 'verifier')
            await runtime.prepare(attempt, ws.worktrees)
            fixture.failures.add('rm')
            self.assertFalse(await runtime.cleanup(attempt))
            self.assertIsNotNone(fixture.process.returncode)
            fixture.failures.clear()
            self.assertTrue(await runtime.cleanup(attempt))
            self.assertTrue(await runtime.cleanup(attempt))
            create = next(c for c in fixture.calls if c[0]=='create')
            self.assertIn('--user=1000:1000', create)
            self.assertIn('--network=none', create)
            self.assertIn('--read-only', create)
            self.assertIn('--log-driver=none', create)
            self.assertFalse(any('sock' in c for c in create))

    def test_capacity_requires_explicit_independent_provider_limits(self):
        with self.assertRaises(Problem):
            capacity(dict(worker=4, frontier=2, verifier=1, repository=1))
        capacity(dict(worker=4, claude=2, codex=2, agy=2, verifier=1, repository=1))

    def test_overlapping_auth_and_management_mounts_are_rejected(self):
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            service = {k:str(ws.root/k) for k in ('state_root','spool_root','repository_root','worktree_root','review_root','bearer_file','capabilities_file')}
            publisher = {'git_binary':'/usr/bin/git', 'git_credential_file':str(ws.root/'git-secret'), 'github_credential_file':str(ws.root/'github-secret')}
            container_settings(settings, ceilings, service, publisher)
            changed = deepcopy(settings)
            changed['credentials']['pi'][0]['mounts'][0]['source'] = service['state_root']
            with self.assertRaises(Problem):
                container_settings(changed, ceilings, service, publisher)
            changed = deepcopy(settings)
            changed['credentials']['pi'][0]['mounts'][0]['target'] = '/run/podman/podman.sock'
            with self.assertRaises(Problem):
                container_settings(changed, ceilings, service, publisher)

    async def test_missing_ledger_recovers_identity_from_launch_journal(self):
        from cursus.runner import Journal, Runner
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            fixture = RuntimeFixture()
            runtime = Containers(settings, ws.state/'runtime', ceilings, fixture)
            journal = Journal(ws.state/'journal')
            execution = type('ExecutionFixture', (), {'runtime':runtime})()
            Runner(str(uuid4()),journal,None,execution=execution)
            attempt = str(uuid4())
            await runtime.reserve(attempt,'worker','pi')
            await runtime.prepare(attempt,ws.worktrees)
            runtime.path.unlink()  # Loss cannot turn a surviving container into absence.
            restarted = Containers(settings,ws.state/'runtime',ceilings,fixture)
            Runner(str(uuid4()),journal,None,execution=type('ExecutionFixture', (), {'runtime':restarted})())
            self.assertIn(attempt,restarted.entries)
            self.assertIsNotNone(restarted.entries[attempt]['id'])
            self.assertTrue((await restarted.recover())[attempt])
            self.assertIsNotNone(fixture.process.returncode)
            journal.close()

    def test_compaction_bounds_history_and_preserves_unresolved_launch(self):
        from cursus.runner import Journal
        with workspace() as ws:
            journal = Journal(ws.state)
            journal.compaction = True
            unresolved = str(uuid4())
            journal.record('grant',dict(attempt_id=unresolved,request_id=str(uuid4())))
            journal.record('launch',unresolved)
            for _ in range(200):
                request, attempt = str(uuid4()),str(uuid4())
                journal.record('pending',dict(id=request,slot='worker'))
                journal.record('grant',dict(attempt_id=attempt,request_id=request))
                journal.record('launch',attempt)
                journal.record('retire',request)
            self.assertEqual(len(journal.records),3)
            self.assertLess(journal.path.stat().st_size,2048)
            generation = journal.generation
            journal.close()
            journal = Journal(ws.state)
            self.assertEqual(journal.generation,generation)
            self.assertIn(dict(kind='launch',value=unresolved),journal.records)
            journal.close()


    def test_production_execution_constructor_has_no_account_inventory(self):
        from cursus.execution import Execution
        runtime = object()
        execution = Execution({'digest':'a'*64}, {}, {'home':'/home/session'}, runtime=runtime)
        self.assertIs(execution.runtime,runtime)
        self.assertEqual(execution.configured({'role':{'cli':'pi','name':'another-coding-role'}})['home'],'/home/session')
        with self.assertRaises(Problem):
            Execution({}, {}, {})

    def test_native_capability_rejects_incomplete_profile_and_sdk_substitution(self):
        from cursus.config import capability
        profile = dict(binary='/usr/local/bin/codex',binary_digest='a'*64,version='fixture-version',
            model='fixture',reasoning='fixture',qualified_roles=['reviewer'],fixed_argv=['exec','--json'],
            prompt_transport='stdin',tool_allowlist=['read'],clean_config_argv=['--fixture-clean'],
            probe_evidence=['fixture-only'],credential_concurrency=2)
        capability('codex',profile)
        with self.assertRaises(Problem):
            capability('codex',dict(profile,fixed_argv=['sdk']))
        with self.assertRaises(Problem):
            capability('codex',dict(profile,probe_evidence=[]))

    async def test_stop_recovery_waits_for_unknown_final_receipt(self):
        from cursus.runner import Journal, Runner
        with workspace() as ws:
            settings, ceilings = policy(ws.root)
            runtime = Containers(settings,ws.state/'runtime',ceilings,RuntimeFixture())
            journal = Journal(ws.state/'journal')
            attempt = str(uuid4())
            journal.record('grant',dict(attempt_id=attempt,request_id=str(uuid4())))
            journal.record('launch',attempt)
            journal.record('container_removed',attempt)
            journal.record('event',dict(attempt_id=attempt,seq=2,kind='final',payload={'kind':'unknown'}))
            journal.record('ack',dict(attempt_id=attempt,committed_through=1))
            observations = []
            class Wire:
                async def exchange(self,route,value,*args):
                    observations.append(value['observations'][0]['kind'])
                    return dict(dispositions={},held_claims=[],commands=[],reconciled=True)
            runner = Runner(str(uuid4()),journal,Wire(),execution=type('Fixture',(),{'runtime':runtime})())
            await runner.reconcile()
            self.assertEqual(observations[-1],'terminal_pending')
            journal.record('ack',dict(attempt_id=attempt,committed_through=2))
            await runner.reconcile()
            self.assertEqual(observations[-1],'stopped')
            journal.close()
