"""Executable external-boundary fixtures, shared by end-to-end tests."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from cursus.contracts import Problem
from cursus.execution import Execution
from cursus.host import HostRuntime
from tests.support import workspace


def criterion():
    return {'id': 'correct', 'requirement': 'Required output exists.',
            'check': {'kind': 'command', 'command_id': 'unit', 'expected_exit': 0}}


# Session ceilings for host-native fixtures (ADR 0016).
CAPACITY = {'worker': 4, 'claude': 2, 'codex': 2, 'agy': 2, 'verifier': 1, 'repository': 1}


async def run(execution, job, workspace, attempt=None, *args, **kwargs):
    """Reserve host capacity as the runner does, then run the job."""
    attempt = attempt or str(uuid4())
    cli = job.get('invocation', {}).get('role', {}).get('cli')
    lane = 'verifier' if job['step'] == 'verify' else ('worker' if cli == 'pi' else cli)
    assert await execution.runtime.reserve(attempt, lane, cli)
    return await execution.run(job, workspace, attempt, *args, **kwargs)


def fixture_execution(ws, overrides=None):
    """Four real executables; no provider credentials or inherited environment."""
    names = ('pi', 'claude', 'codex', 'agy')
    binaries = {}
    plan = {'packages': [{'id': 'one', 'dependencies': [], 'objective': 'Write result.txt',
                         'inputs': [], 'criteria': [criterion()]}], 'phase_check_ids': ['unit']}
    verdict = {'verdict': 'accept', 'criteria': [{'id': 'correct', 'passed': True,
                'evidence': ['Pinned verifier command passed.']}], 'findings': [], 'required_repairs': []}
    values = {'pi': {'summary': 'Wrote result.txt', 'suggested_files': ['result.txt']},
              'claude': plan, 'codex': verdict, 'agy': {'findings': [], 'source_references': []}}
    values.update(overrides or {})
    for cli in names:
        binary = ws.root / cli
        script = f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
assert 'CURSUS_PARENT_SECRET' not in os.environ
cli = {cli!r}
value = {values[cli]!r}
if cli == 'pi':
    frame = json.loads(sys.stdin.readline())
    assert frame['type'] == 'prompt'
    Path('result.txt').write_text('done')
    if 'Task data:' in frame['message']:
        task = json.loads(frame['message'].split('Task data:')[-1])
        if 'package' in task:
            Path(task['package']['id'] + '.txt').write_text('package done')
    print(json.dumps({{'type':'response','id':frame['id'],'success':True}}), flush=True)
    print(json.dumps({{'type':'message_end','message':{{'role':'assistant','content':[{{'type':'text','text':json.dumps(value)}}]}}}}), flush=True)
    print(json.dumps({{'type':'agent_end'}}), flush=True)
    sys.stdin.read()
elif cli == 'codex':
    sys.stdin.read()
    print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':json.dumps(value)}}}}))
    print(json.dumps({{'type':'turn.completed'}}))
else:
    sys.stdin.read()
    print(json.dumps({{'type':'result','subtype':'success','result':json.dumps(value)}}))
'''
        binary.write_text(script)
        binary.chmod(0o755)
        binaries[cli] = str(binary)
    runtime = HostRuntime({'disk_reserve_mb': 1, 'host_reserve_mb': 1}, ws.state / 'execution', dict(CAPACITY))
    return Execution(binaries, runtime)


def invocation(execution, cli, role):
    return {'role': {'name': role, 'cli': cli, 'model': 'fixture', 'reasoning': 'fixture',
                     'tier': 'production' if role == 'worker' else 'organization',
                     'tools': ['read', 'write'] if role == 'worker' else ['read'], 'timeout_seconds': 5},
            'registry_commit': '0' * 40,
            'prompt_text': 'Use only supplied task context.'}


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_wire_formats_and_environment(self):
        with workspace() as ws:
            execution = fixture_execution(ws)
            with patch.dict(os.environ, {'CURSUS_PARENT_SECRET': 'must-not-reach-child'}):
                for cli, role, step in [('pi', 'worker', 'produce'), ('claude', 'planner', 'plan'),
                                        ('codex', 'reviewer', 'review'), ('agy', 'scout', 'scout')]:
                    result = await run(execution, {'step': step, 'input': {'criteria': [criterion()]},
                        'invocation': invocation(execution, cli, role)}, ws.worktrees)
                    self.assertIsInstance(result, dict)
            self.assertEqual((ws.worktrees / 'result.txt').read_text(), 'done')

    async def test_verifier_records_real_exit_and_pinned_candidate(self):
        with workspace() as ws:
            execution = fixture_execution(ws)
            candidate = {'kind': 'code', 'head_sha': '1' * 40}
            job = {'step': 'verify', 'input': {'candidate': candidate, 'criteria': [criterion()],
                   'checks': [{'id': 'unit', 'argv': ['/usr/bin/false'], 'cwd': '.', 'timeout_seconds': 2}]}}
            evidence = await run(execution, job, ws.worktrees)
            self.assertFalse(evidence[0]['passed'])
            self.assertEqual(evidence[0]['observed_exit'], 1)
            self.assertEqual(evidence[0]['candidate'], candidate)

    async def test_invalid_role_report_review_and_terminal(self):
        with workspace() as ws:
            execution = fixture_execution(ws, {'codex': {'verdict': 'accept'}})
            job = {'step': 'review', 'input': {'criteria': [criterion()]},
                   'invocation': invocation(execution, 'codex', 'reviewer')}
            with self.assertRaises(Problem):
                await run(execution, job, ws.worktrees)
            job['invocation']['role']['tier'] = 'production'
            with self.assertRaises(Problem):
                await run(execution, job, ws.worktrees)
            with self.assertRaises(Problem):
                execution.normalize('codex', b'{"type":"turn.completed"}\n')
