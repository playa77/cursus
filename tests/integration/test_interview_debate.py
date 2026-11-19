import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from cursus.contracts import Problem
from cursus.http import request_local
from tests.phase_support import phase_runtime, drive, phase_state
from tests.support import code_input
from tests.integration.test_execution import criterion


def conversation_binaries(rt, blocking=False, amendments=False, spec_question=False, bad_seat=False):
    plan={'packages':[dict(id='one',dependencies=[],objective='Write result.txt',inputs=[],criteria=[criterion()])],
          'phase_check_ids':['unit']}
    for cli in ('claude','codex','agy'):
        binary=Path(rt['execution'].profiles[cli]['binary'])
        binary.write_text(f'''#!{sys.executable}
import json,sys
prompt=sys.stdin.read()
task=json.loads(prompt.split('Task data:')[-1])
plan={plan!r}
seat=task.get('seat')
if seat=='rationale':
    value={{'rationale':'Criteria cover the required output.'}}
elif seat=='critic':
    assert 'responses' not in task and 'judgment' not in task
    value={{'objections':[{{'id':'o1','severity':'blocker','evidence':'Missing requirement','fix':'Add it'}}] if {blocking!r} else []}}
elif seat=='reply':
    value={{'responses':[{{'id':o['id'],'disposition':'amend','rationale':'Will fix'}} for o in task['objections']]}}
elif seat=='judge':
    value={{'rulings':[{{'id':o['id'],'upheld':True,'rationale':'Confirmed'}} for o in task['objections']],
        'required_amendments':['Retain criteria and clarify requirement'] if {amendments!r} else [],
        'questions':[{{'text':'Which audience?','required':True}}] if {spec_question!r} and task['mode']=='spec' and task['round']==1 else [],'verdict':'continue' if {blocking!r} else 'accept'}}
elif seat=='revision':
    value=plan if task['mode']=='plan' else {{'kind':'complete','text':'Amended specification'}}
elif 'transcript' in task:
    value={{'kind':'complete','text':'Implement result for the specified audience.'}} if task['transcript'] else {{'kind':'questions','questions':[{{'text':'What result?','required':True}}]}}
elif 'candidate' in task:
    value={{'verdict':'accept','criteria':[{{'id':c['id'],'passed':True,'evidence':['Inspected exact candidate and checks']}} for c in task['criteria']],'findings':[],'required_repairs':[]}}
else:
    value=plan
if {bad_seat!r} and seat=='critic':
    value={{'rationale':'Wrong seat shape'}}
if {cli!r}=='codex':
    print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':json.dumps(value)}}}}))
    print(json.dumps({{'type':'turn.completed'}}))
else:
    print(json.dumps({{'type':'result','subtype':'success','result':json.dumps(value)}}))
''')
        rt['execution'].profiles[cli]['binary_digest']=sha256(binary.read_bytes()).hexdigest()


async def answer(rt):
    phase=await phase_state(rt)
    question=phase['questions'][0]
    value=dict(kind='answer',phase_id=rt['phase_id'],question_id=question['id'],text='Required working output for engineers.')
    return await asyncio.to_thread(request_local,str(rt['ws'].root/'operator.sock'),'/operator/actions',value,str(uuid4()))


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_guided_questions_answer_and_complete_spec(self):
        value=code_input(); value['source']={'kind':'interview'}
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt)
            phase=await drive(rt,lambda p:bool(p.get('questions')))
            self.assertNotIn('plan',phase)
            self.assertEqual(phase['state'],'intake')
            await answer(rt)
            with self.assertRaises(Problem):
                await answer(rt)
            phase=await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual(len(phase['interviews']),3)
            self.assertEqual(phase['spec_revision'],2)

    async def test_distinct_seat_amendment_then_delivery(self):
        value=code_input(); value['plan_debate']=True
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt,amendments=True)
            phase=await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual([r['input']['seat'] for r in phase['debate_history']],
                             ['rationale','critic','reply','judge','revision'])
            self.assertEqual(len({r['attempt_id'] for r in phase['debate_history']}),5)
            self.assertEqual({phase['roles'][r['role']]['cli'] for r in phase['debate_history']},{'claude','codex','agy'})

    async def test_unresolved_blockers_park_at_three_rounds(self):
        value=code_input(); value['plan_debate']=True
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt,blocking=True,amendments=True)
            phase=await drive(rt)
            self.assertEqual(phase['state'],'parked')
            self.assertEqual(phase['debate']['round'],3)
            self.assertEqual(len(phase['debate_history']),15)
            self.assertEqual(rt['remote'].prs,[])

    async def test_spec_judge_questions_update_revision_before_next_round(self):
        value=code_input(); value['spec_debate']=True
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt,spec_question=True)
            phase=await drive(rt,lambda p:bool(p.get('questions')))
            self.assertEqual(phase['debate']['round'],1)
            await answer(rt)
            phase=await drive(rt)
            self.assertEqual(phase['state'],'delivered',phase.get('reason'))
            self.assertEqual(phase['debate']['round'],2)
            self.assertGreater(phase['spec_revision'],2)

    async def test_wrong_seat_shape_parks(self):
        value=code_input(); value['plan_debate']=True
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt,bad_seat=True)
            phase=await drive(rt)
            self.assertEqual(phase['state'],'parked')
            self.assertEqual(rt['remote'].prs,[])
