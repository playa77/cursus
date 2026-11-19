"""Executable external-boundary fixtures, shared by end-to-end tests."""

import json
import os
from pathlib import Path
import pwd
import sys
import unittest
from hashlib import sha256
from unittest.mock import patch
from uuid import uuid4

from cursus.contracts import Problem
from cursus.execution import Execution
from tests.support import workspace


def criterion():
    return {'id': 'correct', 'requirement': 'Required output exists.',
            'check': {'kind': 'command', 'command_id': 'unit', 'expected_exit': 0}}


def fixture_execution(ws, overrides=None):
    """Four real executables; no provider credentials or inherited environment."""
    user = pwd.getpwuid(os.getuid())
    identities = {cli: {'user': user.pw_name, 'home': str(ws.root)} for cli in ('pi', 'claude', 'codex', 'agy')}
    profiles = {'digest': 'a' * 64}
    plan = {'packages': [{'id': 'one', 'dependencies': [], 'objective': 'Write result.txt',
                         'inputs': [], 'criteria': [criterion()]}], 'phase_check_ids': ['unit']}
    verdict = {'verdict': 'accept', 'criteria': [{'id': 'correct', 'passed': True,
                'evidence': ['Pinned verifier command passed.']}], 'findings': [], 'required_repairs': []}
    values = {'pi': {'summary': 'Wrote result.txt', 'suggested_files': ['result.txt']},
              'claude': plan, 'codex': verdict, 'agy': {'findings': [], 'source_references': []}}
    values.update(overrides or {})
    for cli in identities:
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
        profiles[cli] = {'binary': str(binary), 'binary_digest': sha256(binary.read_bytes()).hexdigest(),
            'model': 'fixture', 'reasoning': 'fixture', 'qualified_roles': ['worker', 'planner', 'reviewer', 'scout'],
            'tool_allowlist': ['read', 'write'] if cli == 'pi' else ['read'], 'fixed_argv': [], 'clean_config_argv': ['--clean'],
            'read_only_argv': ['--read-only'], 'prompt_transport': 'rpc' if cli == 'pi' else 'stdin',
            'probe_evidence': ['controlled-executable-fixture']}
    return Execution(profiles, identities, identities['codex'], allow_test_identity=True)


def invocation(execution, cli, role):
    return {'role': {'name': role, 'cli': cli, 'model': 'fixture', 'reasoning': 'fixture',
                     'tier': 'production' if role == 'worker' else 'organization',
                     'tools': ['read', 'write'] if role == 'worker' else ['read'], 'timeout_seconds': 5},
            'registry_commit': '0' * 40, 'profile_digest': execution.profiles['digest'],
            'prompt_text': 'Use only supplied task context.'}


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_wire_formats_and_environment(self):
        with workspace() as ws:
            execution = fixture_execution(ws)
            with patch.dict(os.environ, {'CURSUS_PARENT_SECRET': 'must-not-reach-child'}):
                for cli, role, step in [('pi', 'worker', 'produce'), ('claude', 'planner', 'plan'),
                                        ('codex', 'reviewer', 'review'), ('agy', 'scout', 'scout')]:
                    result = await execution.run({'step': step, 'input': {'criteria': [criterion()]},
                        'invocation': invocation(execution, cli, role)}, ws.worktrees, str(uuid4()))
                    self.assertIsInstance(result, dict)
            self.assertEqual((ws.worktrees / 'result.txt').read_text(), 'done')

    async def test_verifier_records_real_exit_and_pinned_candidate(self):
        with workspace() as ws:
            execution = fixture_execution(ws)
            candidate = {'kind': 'code', 'head_sha': '1' * 40}
            job = {'step': 'verify', 'input': {'candidate': candidate, 'criteria': [criterion()],
                   'checks': [{'id': 'unit', 'argv': ['/usr/bin/false'], 'cwd': '.', 'timeout_seconds': 2}]}}
            evidence = await execution.run(job, ws.worktrees, str(uuid4()))
            self.assertFalse(evidence[0]['passed'])
            self.assertEqual(evidence[0]['observed_exit'], 1)
            self.assertEqual(evidence[0]['candidate'], candidate)

    async def test_invalid_role_report_review_and_terminal(self):
        with workspace() as ws:
            execution = fixture_execution(ws, {'codex': {'verdict': 'accept'}})
            job = {'step': 'review', 'input': {'criteria': [criterion()]},
                   'invocation': invocation(execution, 'codex', 'reviewer')}
            with self.assertRaises(Problem):
                await execution.run(job, ws.worktrees, str(uuid4()))
            job['invocation']['role']['tier'] = 'production'
            with self.assertRaises(Problem):
                await execution.run(job, ws.worktrees, str(uuid4()))
            with self.assertRaises(Problem):
                execution.normalize('codex', b'{"type":"turn.completed"}\n')
