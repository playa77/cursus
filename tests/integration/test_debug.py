import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from tests.support import code_input
from tests.phase_support import phase_runtime, drive, phase_state


class DebugTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, cancel=False, first_pass=False, turn_cap=False, abandon=False):
        value = code_input()
        value.update(workflow='debug')
        del value['form']
        async with phase_runtime(value=value) as rt:
            if turn_cap:
                rt['config']['limits']['debug_turns']=1
            binary = Path(rt['execution'].profiles['pi']['binary'])
            binary.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
turn=0
for line in sys.stdin:
    frame=json.loads(line)
    print(json.dumps({{'type':'response','id':frame['id'],'success':True}}),flush=True)
    if frame['type']=='steer':
        continue
    turn+=1
    Path('process.txt').write_text(str(os.getpid()))
    Path('result.txt').write_text('broken' if turn==1 and not {first_pass!r} else 'done')
    value={{'summary':'Debug turn '+str(turn),'suggested_files':['result.txt']}}
    print(json.dumps({{'type':'message_end','message':{{'role':'assistant','content':[{{'type':'text','text':json.dumps(value)}}]}}}}),flush=True)
    print(json.dumps({{'type':'agent_end'}}),flush=True)
''')
            rt['execution'].profiles['pi']['binary_digest'] = sha256(binary.read_bytes()).hexdigest()
            await drive(rt,lambda p:p['state']=='execution')
            claim = await rt['runner'].claim('worker')
            self.assertEqual(claim['job']['step'],'debug')
            task = asyncio.create_task(rt['runner'].dispatch(claim))
            try:
                seen = []
                for _ in range(100):
                    phase = await phase_state(rt)
                    if phase.get('debug_checkpoint'):
                        if abandon:
                            await rt['control'].action('local_operator',str(uuid4()),{'kind':'declare_unrecoverable','attempt_id':claim['attempt_id'],'reason':'Isolated recovery scenario'})
                            await rt['control'].action('local_operator',str(uuid4()),{'kind':'abandon','attempt_id':claim['attempt_id'],'reason':'Invalidate original ownership'})
                            directive=await rt['runner'].reconcile()
                            self.assertEqual(directive['dispositions'][claim['attempt_id']],'stop-stale')
                            break
                        if cancel:
                            await rt['control'].action('local_operator',str(uuid4()),{'kind':'cancel','phase_id':rt['phase_id']})
                            directive=await rt['runner'].reconcile()
                            await rt['runner'].apply_commands(directive['commands'])
                            await rt['runner'].apply_commands(directive['commands'])
                            break
                        verify = await rt['runner'].claim('verifier')
                        if verify:
                            final = await rt['runner'].dispatch(verify)
                            seen.append(final['value'][0]['passed'])
                            directive=await rt['runner'].reconcile()
                            await rt['runner'].apply_commands(directive['commands'])
                            await rt['runner'].apply_commands(directive['commands'])
                    if task.done():
                        break
                    await asyncio.sleep(.02)
                await asyncio.wait_for(task,5)
                phase=await phase_state(rt)
                if abandon:
                    old=(await rt['db'].store.read('attempts',claim['attempt_id']))['items'][0]
                    self.assertEqual(old['status'],'abandoned')
                    self.assertNotIn('candidate',phase)
                    self.assertEqual(rt['remote'].prs,[])
                elif cancel:
                    self.assertEqual(phase['state'],'canceled',phase)
                    self.assertEqual(rt['remote'].prs,[])
                elif first_pass or turn_cap:
                    self.assertEqual(seen,[True] if first_pass else [False])
                    self.assertEqual(phase['state'],'parked')
                    self.assertEqual(rt['remote'].prs,[])
                else:
                    self.assertEqual(seen,[False,True])
                    phase=await drive(rt)
                    self.assertEqual(phase['state'],'delivered',phase.get('reason'))
                    self.assertEqual(phase['candidate'],phase['debug_checkpoint']['candidate'])
                    self.assertEqual(phase['debug_checkpoint']['turn'],2)
                    debug_attempts=[a for a in (await rt['db'].store.read('attempts'))['items'] if a['claim']['job']['step']=='debug']
                    self.assertEqual(len(debug_attempts),1)
                    committed = (await rt['db'].store.read('events', rt['phase_id']))['items']
                    checkpoints=[r['payload']['payload']['candidate'] for r in committed if r['kind']=='debug_checkpoint']
                    pids=[rt['remote'].git(rt['remote'].remote,'show',c['attempt_ref']+':process.txt') for c in checkpoints]
                    self.assertEqual(len(pids),2)
                    self.assertEqual(pids[0],pids[1])
                    self.assertEqual(len(rt['remote'].prs),1)
                    commands=(await rt['db'].store.read('commands'))['items']
                    self.assertEqual([c['state'] for c in commands],['accepted','accepted'])
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)

    async def test_same_rpc_failing_then_passing_checkpoint_to_pr(self):
        await self.scenario()

    async def test_cancel_stops_held_rpc_before_canceled(self):
        await self.scenario(cancel=True)

    async def test_missing_reproduction_parks_without_pr(self):
        await self.scenario(first_pass=True)

    async def test_turn_cap_parks_and_stops_rpc(self):
        await self.scenario(turn_cap=True)

    async def test_abandoned_live_rpc_stops_and_cannot_advance(self):
        await self.scenario(abandon=True)
