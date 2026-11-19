import unittest
from uuid import uuid4
from cursus.contracts import Problem
from tests.phase_support import phase_runtime, drive, phase_state


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_claim_and_final_ack_reuse_attempt(self):
        async with phase_runtime() as rt:
            runner = rt['runner']
            original = runner.exchange
            async def lose_claim(route, *args, **kwargs):
                result = await original(route,*args,**kwargs)
                if route == 'jobs/next' and result:
                    raise OSError('Lost committed grant response')
                return result
            runner.exchange = lose_claim
            with self.assertRaises(OSError):
                await runner.claim('repository')
            runner.exchange = original
            directive = await runner.reconcile()
            self.assertEqual(len(directive['held_claims']),1)
            claim = directive['held_claims'][0]
            runner.record('grant',claim)
            async def lose_ack(route,*args,**kwargs):
                result = await original(route,*args,**kwargs)
                if route.endswith('/events'):
                    raise OSError('Lost committed event acknowledgment')
                return result
            runner.exchange = lose_ack
            with self.assertRaises(OSError):
                await runner.dispatch(claim)
            runner.exchange = original
            await rt['control'].maintain('boot')
            await runner.reconcile()
            await runner.replay()
            await runner.reconcile()
            attempts = (await rt['db'].store.read('attempts'))['items']
            self.assertEqual(len(attempts),1)
            self.assertEqual(attempts[0]['id'],claim['attempt_id'])
            phase = await drive(rt)
            self.assertEqual(phase['state'],'delivered')
            self.assertEqual(len(rt['remote'].prs),1)

    async def test_unknown_requires_abandon_and_late_final_is_stale(self):
        async with phase_runtime() as rt:
            runner, control = rt['runner'], rt['control']
            claim = await runner.claim('repository')
            attempt_id = claim['attempt_id']
            await control.action('local_operator',str(uuid4()),dict(kind='declare_unrecoverable',
                attempt_id=attempt_id,reason='Unknown process state'))
            self.assertIsNone(await runner.claim('repository'))
            row = (await rt['db'].store.read('attempts',attempt_id))['items'][0]
            self.assertEqual(row['status'],'unknown')
            await control.action('local_operator',str(uuid4()),dict(kind='abandon',
                attempt_id=attempt_id,reason='Operator isolated old execution'))
            await runner.event(attempt_id,'final',{'kind':'completed','value':{'base_sha':rt['remote'].base,'text':'late'}})
            await runner.replay()
            phase = await phase_state(rt)
            self.assertNotIn('spec',phase)
            phase = await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))

    async def test_proven_stop_retries_with_new_claim(self):
        async with phase_runtime() as rt:
            claim = await rt['runner'].claim('repository')
            directive = await rt['runner'].exchange(f"runners/{rt['runner'].id}/reconcile",{
                'generation':rt['journal'].generation,'pending_request_ids':[],
                'observations':[{'attempt_id':claim['attempt_id'],'kind':'stopped',
                                 'reason':'Changed boot identity proves prior processes stopped.'}]})
            self.assertTrue(directive['reconciled'])
            replacement = await rt['runner'].claim('repository')
            self.assertNotEqual(replacement['attempt_id'],claim['attempt_id'])
            await rt['runner'].dispatch(replacement)
            self.assertEqual((await drive(rt))['state'],'delivered')

    async def test_ambiguous_pr_is_reconciled_without_second_post(self):
        async with phase_runtime() as rt:
            await drive(rt, lambda p:p['state']=='delivery' and p.get('intent',{}).get('kind')=='publish_pr')
            original = rt['remote'].request
            def lose_post(method,path,body=None):
                result = original(method,path,body)
                if method == 'POST':
                    raise Problem('publication_unknown','Lost creation response')
                return result
            rt['remote'].request = lose_post
            claim = await rt['runner'].claim('repository')
            await rt['runner'].dispatch(claim)
            self.assertEqual((await phase_state(rt))['state'],'parked')
            rt['remote'].request = original
            claim = await rt['runner'].claim('repository')
            self.assertEqual(claim['job']['step'],'reconcile_publication')
            await rt['runner'].dispatch(claim)
            self.assertEqual((await phase_state(rt))['state'],'delivered')
            self.assertEqual(len([r for r in rt['remote'].requests if r[0]=='POST']),1)
