"""Real service/Git/process harness for M2 fault scenarios."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from uuid import uuid4
from cursus.control import Control
from cursus.runner import Journal, Runner
from tests.support import Database, SocketService, workspace, settings, code_input, GitRemote
from tests.integration.test_runner_transport import Wire
from tests.integration.test_execution import CAPACITY, fixture_execution, invocation, criterion


LANES = ('repository','claude','codex','agy','worker','verifier')


@asynccontextmanager
async def phase_runtime(overrides=None, value=None):
    async with Database() as db:
        with workspace() as ws:
            remote = GitRemote(ws.root)
            (remote.seed/'result.txt').write_text('done')
            remote.git(remote.seed, 'add', '.')
            remote.git(remote.seed, 'commit', '-m', 'Passing baseline for independent edits')
            remote.git(remote.seed, 'push', 'origin', 'main')
            remote.base = remote.git(remote.seed, 'rev-parse', 'HEAD')
            repository = remote.repository(ws)
            execution = fixture_execution(ws, overrides)
            config = settings()
            config['capacity'] = dict(CAPACITY)
            config['roles'] = {name: dict(invocation(execution, cli, name)['role'], prompt_text='Fixture role.')
                for name, cli in [('worker','pi'), ('debug','pi'), ('planner','claude'),
                    ('interviewer','claude'), ('reviewer','codex'), ('advocate','claude'),
                    ('critic','codex'), ('judge','agy')]}
            config['roles']['debug'].update(tier='production', tools=['read','write'])
            config['repositories'][0]['checks'][0]['argv'] = [sys.executable, 'check.py']
            from cursus.artifacts import Artifacts
            control = Control(config, db.store, artifacts=Artifacts(ws.artifacts))
            journal = Journal(ws.state)
            try:
                async with SocketService(control, ws.root/'operator.sock'), SocketService(control, ws.root/'runner.sock', False):
                    from cursus.http import request_local
                    reply = await asyncio.to_thread(request_local, str(ws.root/'operator.sock'), '/operator/actions',
                        {'kind':'submit','input':value or code_input()}, str(uuid4()))
                    runner = Runner(config['runner']['id'], journal,
                        Wire(ws.root/'runner.sock', journal.generation), repository, execution)
                    await runner.reconcile()
                    yield dict(db=db, ws=ws, remote=remote, repository=repository, execution=execution,
                               config=config, control=control, journal=journal, runner=runner, phase_id=reply['entity_id'])
            finally:
                journal.close()


async def phase_state(rt):
    return (await rt['control'].query('local_operator','phases',rt['phase_id']))['items'][0]


async def drive(rt, until=None, limit=100):
    for _ in range(limit):
        phase = await phase_state(rt)
        if (until and until(phase)) or phase['state'] in ('delivered','parked','canceled'):
            return phase
        found = False
        for slot in LANES:
            claim = await rt['runner'].claim(slot)
            if claim:
                found = True
                await rt['runner'].dispatch(claim)
                phase = await phase_state(rt)
                if until and until(phase):
                    return phase
        if not found:
            raise AssertionError('No claimable work before outcome')
    raise AssertionError('Scenario step budget exhausted')


def packages():
    return {'packages': [dict(id=name, dependencies=deps, objective='Write result.txt',
        inputs=[], criteria=[criterion()]) for name,deps in [('one',[]),('two',[]),('three',['one','two'])]],
        'phase_check_ids':['unit']}
