"""Per-provider and worker caps exercised through real intake/claim/event paths."""
import asyncio
from copy import deepcopy
import os
import pwd
import unittest
from uuid import uuid4
from cursus.contracts import Problem
from cursus.identities import IdentityPool
from tests.phase_support import phase_runtime, drive, phase_state
from tests.support import code_input
from tests.integration.test_execution import invocation, criterion


def maximum():
    return dict(worker=4,claude=2,codex=2,agy=2,pi=1,verifier=1,repository=1)


def configure(rt):
    rt['config']['runner']['capacity']=maximum()
    rt['runner'].capacity=maximum()
    # External Unix identity boundary fixture: same test UID, distinct logical
    # leases/private homes. This does not claim live cross-UID isolation.
    user=pwd.getpwuid(os.getuid())
    accounts=[dict(id=f'fixture-{i}',user=user.pw_name,home=str(rt['ws'].root/f'identity-{i}')) for i in range(16)]
    rt['execution'].pool=accounts
    rt['execution'].home_root=rt['ws'].root/'homes'
    rt['runner'].pool=IdentityPool(accounts,rt['journal'])


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_per_provider_are_independent_and_unknown_still_counts(self):
        async with phase_runtime() as rt:
            configure(rt)
            await rt['runner'].reconcile()
            resolve=await rt['runner'].claim('repository',wait=False)
            await rt['runner'].dispatch(resolve)
            # Existing phase supplies first Claude job; create every other plan
            # through production intake and source resolution, never fixture rows.
            for cli in ('claude','claude','codex','codex','codex','agy','agy','agy'):
                rt['config']['roles']['planner']=dict(invocation(rt['execution'],cli,'planner')['role'],prompt_text='Fixture role.')
                await rt['control'].action('local_operator',str(uuid4()),dict(kind='submit',input=code_input()))
                claim=await rt['runner'].claim('repository',wait=False)
                await rt['runner'].dispatch(claim)
            claims=[]
            for cli in ('claude','codex','agy'):
                for _ in range(2):
                    claim=await rt['runner'].claim('frontier',provider=cli,wait=False)
                    self.assertIsNotNone(claim)
                    self.assertEqual(claim['job']['invocation']['role']['cli'],cli)
                    claims.append(claim)
                self.assertIsNone(await rt['runner'].claim('frontier',provider=cli,wait=False))
            await rt['control'].action('local_operator',str(uuid4()),dict(kind='declare_unrecoverable',
                attempt_id=claims[0]['attempt_id'],reason='Simulated permanently unknown outcome.'))
            self.assertIsNone(await rt['runner'].claim('frontier',provider='claude',wait=False))
            original=rt['execution'].run
            entered=0
            barrier=asyncio.Event()
            async def overlap(*args,**kwargs):
                nonlocal entered
                entered+=1
                if entered==6:
                    barrier.set()
                await asyncio.wait_for(barrier.wait(),5)
                return await original(*args,**kwargs)
            rt['execution'].run=overlap
            results=await asyncio.gather(*(rt['runner'].dispatch(claim) for claim in claims))
            self.assertTrue(all(r['kind']=='completed' for r in results))
            leases=[r['value'] for r in rt['journal'].records if r['kind']=='identity_lease']
            self.assertEqual(len({r['index'] for r in leases}),6)
            self.assertEqual(rt['runner'].pool.held,{})

    async def test_four_workers_execute_with_four_leases_and_fifth_waits(self):
        plan=dict(packages=[dict(id=f'p{i}',dependencies=[],objective='Write output',inputs=[],criteria=[criterion()])
                            for i in range(5)],phase_check_ids=['unit'])
        value=code_input(); value['form']='phase'
        async with phase_runtime({'claude':plan},value) as rt:
            configure(rt)
            await rt['runner'].reconcile()
            await drive(rt,lambda p:'schedule' in p)
            claims=[await rt['runner'].claim('worker',wait=False) for _ in range(4)]
            self.assertTrue(all(claims))
            self.assertIsNone(await rt['runner'].claim('worker',wait=False))
            results=await asyncio.gather(*(rt['runner'].dispatch(c) for c in claims))
            self.assertTrue(all(r['kind']=='completed' for r in results))
            leases=[r['value'] for r in rt['journal'].records if r['kind']=='identity_lease']
            worker_ids={c['attempt_id'] for c in claims}
            self.assertEqual(len({r['index'] for r in leases if r['attempt_id'] in worker_ids}),4)
            self.assertIsNotNone(await rt['runner'].claim('worker',wait=False))

    async def test_capacity_mismatch_fails_before_new_claims(self):
        async with phase_runtime() as rt:
            rt['runner'].capacity=maximum()
            with self.assertRaises(Problem) as caught:
                await rt['runner'].reconcile()
            self.assertEqual(caught.exception.code,'state_conflict')

    async def test_unknown_process_holds_uid_across_restart_and_abandonment(self):
        from cursus.runner import Runner
        from cursus.journal import Journal
        async with phase_runtime() as rt:
            configure(rt)
            await rt['runner'].reconcile()
            await drive(rt,lambda p:p['state']=='execution')
            original=rt['execution'].run
            async def unknown(*args,**kwargs):
                raise Problem('unknown_stop','Fixture process group outcome is unknown.')
            rt['execution'].run=unknown
            claim=await rt['runner'].claim('worker',wait=False)
            result=await rt['runner'].dispatch(claim)
            self.assertEqual(result['kind'],'unknown')
            self.assertIn(claim['attempt_id'],rt['runner'].pool.held)
            old_index=rt['runner'].pool.held[claim['attempt_id']]
            rt['journal'].close()
            journal=Journal(rt['ws'].state)
            rt['journal']=journal
            rt['runner'].journal=journal
            rt['runner'].pool=IdentityPool(rt['execution'].pool,journal)
            try:
                await rt['control'].action('local_operator',str(uuid4()),dict(kind='abandon',
                    attempt_id=claim['attempt_id'],reason='Isolate the stale process, retaining UID quarantine.'))
                await rt['runner'].reconcile()
                self.assertIn(claim['attempt_id'],rt['runner'].pool.held)
                rt['execution'].run=original
                replacement=await rt['runner'].claim('worker',wait=False)
                final=await rt['runner'].dispatch(replacement)
                self.assertEqual(final['kind'],'completed')
                lease=next(r['value'] for r in journal.records if r['kind']=='identity_lease'
                           and r['value']['attempt_id']==replacement['attempt_id'])
                self.assertNotEqual(lease['index'],old_index)
            finally:
                journal.close()

    async def test_waiters_leave_connections_for_operator_reads(self):
        import time
        async with phase_runtime() as rt:
            waits=[asyncio.create_task(rt['db'].store.wait(time.monotonic()+1,999999)) for _ in range(12)]
            try:
                async with asyncio.timeout(1):
                    await rt['control'].query('local_operator','phases',rt['phase_id'])
            finally:
                for task in waits:
                    task.cancel()
                await asyncio.gather(*waits,return_exceptions=True)

    async def test_changed_boot_releases_unknown_identity_only_after_reconciliation(self):
        async with phase_runtime() as rt:
            configure(rt)
            await rt['runner'].reconcile()
            await drive(rt,lambda p:p['state']=='execution')
            async def unknown(*args,**kwargs):
                raise Problem('unknown_stop','Fixture unknown process group.')
            rt['execution'].run=unknown
            claim=await rt['runner'].claim('worker',wait=False)
            await rt['runner'].dispatch(claim)
            self.assertIn(claim['attempt_id'],rt['runner'].pool.held)
            rt['runner'].boot_id='fixture-new-boot'
            await rt['runner'].reconcile()
            self.assertNotIn(claim['attempt_id'],rt['runner'].pool.held)

    async def test_live_logs_reach_control_before_worker_completion(self):
        async with phase_runtime() as rt:
            await drive(rt,lambda p:p['state']=='execution')
            binary=rt['execution'].profiles['pi']['binary']
            from hashlib import sha256
            from pathlib import Path
            path=Path(binary)
            source=path.read_text().replace("    assert frame['type'] == 'prompt'", "    print(json.dumps({'type':'progress','message':'fixture live progress'}),flush=True)\n    import time; time.sleep(3)\n    assert frame['type'] == 'prompt'")
            path.write_text(source)
            rt['execution'].profiles['pi']['binary_digest']=sha256(path.read_bytes()).hexdigest()
            claim=await rt['runner'].claim('worker',wait=False)
            worker=asyncio.create_task(rt['runner'].dispatch(claim))
            pump=asyncio.create_task(rt['runner'].event_pump())
            try:
                async with asyncio.timeout(3):
                    while True:
                        events=await rt['control'].query('local_operator','events',rt['phase_id'])
                        if any(e['kind']=='log' and 'fixture live progress' in str(e['payload']) for e in events['items']):
                            break
                        await asyncio.sleep(.05)
                self.assertFalse(worker.done())
                self.assertEqual((await worker)['kind'],'completed')
            finally:
                pump.cancel()
                worker.cancel()
                await asyncio.gather(pump,worker,return_exceptions=True)

    async def test_controller_installer_database_role_sql_is_repeatable(self):
        from tests.unit.test_execution_pool import RecordingInstaller
        from tests.support import Database
        installer=RecordingInstaller('control')
        installer.install()
        sql=next(command[-1] for command in installer.commands if command[-1].startswith('DO $$'))
        async with Database() as db:
            # Exercise the real generated provisioning SQL, rolled back in the
            # task-owned PostgreSQL fixture. No OS accounts or databases created.
            transaction=db.admin.transaction()
            await transaction.start()
            try:
                await db.admin.execute(sql)
                await db.admin.execute(sql)
                row=await db.admin.fetchrow("SELECT rolsuper,rolcreatedb,rolcreaterole,rolcanlogin FROM pg_roles WHERE rolname='cursus-control'")
                self.assertEqual(tuple(row),(False,False,False,True))
            finally:
                await transaction.rollback()
