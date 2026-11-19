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
