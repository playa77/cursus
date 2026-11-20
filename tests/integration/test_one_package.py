import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from cursus.control import Control
from cursus.runner import Journal, LocalTransport, Runner
from tests.support import Database, SocketService, workspace, settings, code_input, GitRemote
from tests.integration.test_execution import CAPACITY, fixture_execution, invocation


class OnePackageTests(unittest.IsolatedAsyncioTestCase):
    async def run_phase(self, source='inline', overrides=None, drift=False):
        async with Database() as db:
            with workspace() as ws:
                remote = GitRemote(ws.root)
                repository = remote.repository(ws)
                execution = fixture_execution(ws, overrides)
                config = settings()
                config['capacity'] = dict(CAPACITY)
                config['roles'] = {name: dict(invocation(execution, cli, name)['role'], prompt_text='Fixture role.')
                                   for name, cli in [('worker', 'pi'), ('planner', 'claude'), ('reviewer', 'codex')]}
                config['repositories'][0]['checks'][0]['argv'] = [sys.executable, 'check.py']
                from cursus.artifacts import Artifacts
                control = Control(config, db.store, artifacts=Artifacts(ws.artifacts))
                value = code_input()
                if source == 'repo':
                    value['source'] = {'kind': 'repo', 'owner': 'fixture', 'name': 'repo',
                                       'commit': remote.base, 'path': 'spec.md'}
                input_path = ws.root / 'input.json'
                input_path.write_text(json.dumps(value))
                journal = Journal(ws.state)
                try:
                    async with SocketService(control, ws.root / 'operator.sock'):
                        env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(Path('src').resolve())}
                        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'cursus.bootstrap',
                            'submit', '--socket', str(ws.root / 'operator.sock'), '--input', str(input_path),
                            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        stdout, stderr = await process.communicate()
                        self.assertEqual(process.returncode, 0, stderr.decode())
                        phase_id = json.loads(stdout)['entity_id']
                        runner = Runner(config['runner']['id'], journal,
                            LocalTransport(control, config['runner']['id'], journal.generation), repository, execution)
                        await runner.reconcile()
                        moved=False
                        for _ in range(30):
                            view = await control.query('local_operator', 'phases', phase_id)
                            phase = view['items'][0]
                            if phase['state'] in ('delivered', 'parked'):
                                break
                            claimed = False
                            for slot in ('repository', 'claude', 'codex', 'agy', 'worker', 'verifier'):
                                claim = await runner.claim(slot)
                                if claim:
                                    claimed = True
                                    if drift and not moved and claim['job']['step'] == 'inspect_target':
                                        moved=True
                                        (remote.seed / 'new.txt').write_text('target drift')
                                        remote.git(remote.seed, 'add', '.')
                                        remote.git(remote.seed, 'commit', '-m', 'Target moved')
                                        remote.git(remote.seed, 'push', 'origin', 'main')
                                    await runner.dispatch(claim)
                            self.assertTrue(claimed, 'Pipeline stalled without queued work.')
                        else:
                            self.fail('Pipeline exceeded bounded test step count')
                        attempts = (await db.store.read('attempts'))['items']
                        publications = (await db.store.read('publications'))['items']
                        # Replay process-produced events through the ordinary API.
                        await runner.replay()
                        self.assertTrue(all(a['status'] == 'terminal' for a in attempts))
                        if drift:
                            self.assertEqual(phase['state'], 'delivered',phase.get('reason'))
                            self.assertEqual(len(remote.prs),1)
                            self.assertEqual(phase['drift_count'],1)
                            self.assertEqual(phase['references'][0]['head_sha'],phase['staged']['head_sha'])
                            self.assertEqual(phase['integration_review']['verdict'],'accept')
                        elif overrides:
                            self.assertEqual(phase['state'], 'parked', phase.get('reason'))
                            self.assertEqual(remote.prs, [])
                            self.assertEqual(publications, [])
                        else:
                            self.assertEqual(phase['state'], 'delivered', phase.get('reason'))
                            self.assertEqual(len(remote.prs), 1)
                            self.assertEqual(phase['references'][0]['head_sha'], phase['staged']['head_sha'])
                            self.assertEqual(remote.git(remote.remote, 'rev-parse', 'main'), remote.base)
                            self.assertTrue(phase['evidence'][0]['passed'])
                            self.assertEqual(phase['review']['verdict'], 'accept')
                            self.assertEqual([p['state'] for p in publications], ['confirmed', 'confirmed'])
                finally:
                    journal.close()

    async def test_inline_to_exact_pr(self):
        await self.run_phase()

    async def test_pinned_repo_to_exact_pr(self):
        await self.run_phase('repo')

    async def test_invalid_review_cannot_publish(self):
        await self.run_phase(overrides={'codex': {'verdict': 'accept'}})

    async def test_target_drift_revalidates_before_publication(self):
        await self.run_phase(drift=True)

    async def test_repair_budget_parks_without_intent(self):
        await self.run_phase(overrides={'codex': {'verdict': 'repair',
            'criteria': [{'id':'correct','passed':False,'evidence':['Output needs repair.']}],
            'findings':['Repair required.'], 'required_repairs':['Repair output.']}})

    async def test_missing_report_cannot_publish(self):
        await self.run_phase(overrides={'pi': {'summary':'', 'suggested_files':[]}})
