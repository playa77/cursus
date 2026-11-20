import asyncio
import unittest
from cursus.contracts import Problem, validate
from tests.support import code_input
from tests.phase_support import phase_runtime, phase_state, drive, packages


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    def test_graph_and_group_validation(self):
        value = packages()
        validate('Plan', value)
        value['packages'][0]['dependencies'] = ['three']
        with self.assertRaises(Problem):
            validate('Plan', value)
        value = packages()
        value['delivery_groups'] = [{'id':'a','package_ids':['one']}, {'id':'b','package_ids':['two','three']}]
        with self.assertRaises(Problem):
            validate('Plan', value)

    async def test_parallel_claims_dependency_head_and_serial_lane(self):
        value = code_input()
        value['form'] = 'phase'
        async with phase_runtime({'claude':packages()}, value) as rt:
            await drive(rt, lambda p: 'schedule' in p)
            first = await rt['runner'].claim('worker')
            second = await rt['runner'].claim('worker')
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first['attempt_id'], second['attempt_id'])
            self.assertEqual([first['job']['package_id'],second['job']['package_id']],['one','two'])
            await asyncio.gather(rt['runner'].dispatch(first), rt['runner'].dispatch(second))
            phase = await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual(len(rt['remote'].prs),1)
            attempts = (await rt['db'].store.read('attempts'))['items']
            produced = [a for a in attempts if a['claim']['job']['step']=='produce']
            self.assertEqual(len(produced),3)
            dependent = next(a for a in produced if a['claim']['job']['package_id']=='three')
            self.assertNotEqual(dependent['claim']['job']['input']['base_sha'],rt['remote'].base)
            refs = [s['candidate']['attempt_ref'] for s in phase['schedule'].values()]
            self.assertEqual(len(set(refs)),3)
            self.assertTrue(all(s['state'] in ('integrated','delivered') for s in phase['schedule'].values()))

    async def test_independent_delivery_groups_publish_distinct_refs(self):
        value=code_input(); value['form']='phase'
        planned=packages(); planned['packages']=planned['packages'][:2]
        planned['delivery_groups']=[{'id':'alpha','package_ids':['one']},{'id':'beta','package_ids':['two']}]
        async with phase_runtime({'claude':planned},value) as rt:
            phase=await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual(len(phase['references']),2)
            self.assertEqual(len({r['head_ref'] for r in phase['references']}),2)
            self.assertTrue(all(g['state']=='delivered' for g in phase['lanes'].values()))

    async def test_target_drift_revalidates_multi_package_before_pr(self):
        value=code_input(); value['form']='phase'
        async with phase_runtime({'claude':packages()},value) as rt:
            await drive(rt,lambda p:'schedule' in p)
            (rt['remote'].seed/'drift.txt').write_text('Moved target')
            rt['remote'].git(rt['remote'].seed,'add','.')
            rt['remote'].git(rt['remote'].seed,'commit','-m','Move target during phase')
            rt['remote'].git(rt['remote'].seed,'push','origin','main')
            phase=await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual(len(rt['remote'].prs),1)
            self.assertTrue(any(s.get('drift_count') for s in phase['schedule'].values()))

    async def test_runner_service_drives_parallel_phase(self):
        value=code_input(); value['form']='phase'
        async with phase_runtime({'claude':packages()},value) as rt:
            rt['config']['limits']['long_poll_seconds']=.01
            identities=[]
            record=rt['execution'].runtime.record
            def spy(kind,value):
                if kind=='execution_identity':
                    identities.append(value)
                return record(kind,value)
            rt['execution'].runtime.record=spy
            task=asyncio.create_task(rt['runner'].serve())
            try:
                async with asyncio.timeout(20):
                    while True:
                        phase=await phase_state(rt)
                        if phase['state'] in ('delivered','parked'):
                            break
                        if task.done():
                            await task
                        await asyncio.sleep(.05)
                self.assertEqual(phase['state'],'delivered',phase.get('reason'))
                # Each package's worker process was identified before its output was read.
                workers=[v for v in identities if v['cli']=='pi']
                self.assertEqual(len(workers),3)
                self.assertTrue(all('start_ticks' in v['process'] for v in workers))
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
