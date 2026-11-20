import unittest
from uuid import uuid4
from cursus.contracts import validate, Problem
from cursus.config import enrollment
from cursus.runner import Journal
from cursus.workflows import plan, evidence
from tests.support import workspace, settings
from tests.integration.test_execution import criterion


class M1ContractsTests(unittest.TestCase):
    def test_plan_preserves_enrolled_checks_and_rejects_command_injection(self):
        catalog = settings()['repositories'][0]
        good = {'packages': [{'id':'one','dependencies':[],'objective':'Fix','inputs':[],
                             'criteria':[criterion()]}], 'phase_check_ids':['unit']}
        self.assertEqual(plan(good, catalog), good)
        import copy
        for mutate in (
            lambda p: p.update(phase_check_ids=[]),
            lambda p: p['packages'][0].update(dependencies=['missing']),
            lambda p: p['packages'][0]['criteria'][0]['check'].update(command_id='agent_shell'),
            lambda p: p['packages'].append(copy.deepcopy(p['packages'][0])),
        ):
            changed = copy.deepcopy(good)
            mutate(changed)
            with self.assertRaises(Problem):
                plan(changed, catalog)

    def test_evidence_cannot_substitute_candidate_or_invent_pass(self):
        attempt = str(uuid4())
        candidate = {'head_sha': '1'*40}
        item = {'criterion_id':'correct','candidate':candidate,'passed':True,
                'observed_exit':0,'output':'','verifier_attempt_id':attempt}
        self.assertTrue(evidence([item], candidate, [criterion()], attempt))
        with self.assertRaises(Problem):
            evidence([dict(item, observed_exit=1)], candidate, [criterion()], attempt)
        with self.assertRaises(Problem):
            evidence([item], {'head_sha':'2'*40}, [criterion()], attempt)
        with self.assertRaises(Problem):
            evidence([], candidate, [criterion()], attempt)

    def test_journal_torn_tail_and_prior_corruption(self):
        with workspace() as ws:
            journal = Journal(ws.state)
            generation = journal.generation
            journal.record('pending', {'id':str(uuid4()), 'slot':'worker'})
            journal.close()
            path = ws.state / 'journal.jsonl'
            with path.open('ab') as output:
                output.write(b'{"torn":')
            journal = Journal(ws.state)
            self.assertEqual(journal.generation, generation)
            self.assertEqual(len(journal.records), 2)
            journal.close()
            raw = path.read_bytes().replace(b'pending', b'altered')
            path.write_bytes(raw)
            with self.assertRaises(Problem):
                Journal(ws.state)

    def test_closed_runtime_shapes(self):
        with self.assertRaises(Problem):
            validate('Ack', {'committed_through':2, 'next_expected':2, 'disposition':'active'})
        with self.assertRaises(Problem):
            validate('Final', {'kind':'completed','value':{},'reason':'wrong variant'})
        with self.assertRaises(Problem):
            validate('Role', {'name':'reviewer','cli':'codex','tier':'organization','model':'x',
                              'reasoning':'x','tools':['bash'],'timeout_seconds':1})

    def test_control_configuration_pins_prompt_release(self):
        from pathlib import Path
        import shutil
        from cursus.config import load
        from tests.support import GitRemote
        with workspace() as ws:
            remote = GitRemote(ws.root)
            release = remote.seed
            role_text = Path('roles.toml').read_text()
            replacements = {'REPLACE_SHA256_OF_QUALIFIED_PROFILE':'a'*64,
                            'REPLACE_QUALIFIED_MODEL':'fixture', 'REPLACE_QUALIFIED_REASONING':'fixture',
                            'REPLACE_QUALIFIED_OPENCODE_GO_PROVIDER_ID':'fixture-go'}
            for old, new in replacements.items():
                role_text = role_text.replace(old, new)
            (release / 'roles.toml').write_text(role_text)
            shutil.copytree('prompts', release / 'prompts')
            remote.git(release, 'add', '.')
            remote.git(release, 'commit', '-m', 'Fixture role release')
            commit = remote.git(release, 'rev-parse', 'HEAD')
            dsn = ws.root / 'dsn'
            digest = ws.root / 'digest'
            dsn.write_text('postgresql://fixture')
            digest.write_text('a'*64)
            dsn.chmod(0o600)
            digest.chmod(0o600)
            text = Path('deploy/control.example.toml').read_text()
            for old, new in {
                '/opt/cursus/current/source/roles.toml':str(release/'roles.toml'),
                '/opt/cursus/current/source/prompts':str(release/'prompts'),
                '/etc/cursus/control/database-dsn':str(dsn),
                '/etc/cursus/control/runner-bearer.sha256':str(digest),
                'REPLACE_FULL_RELEASE_COMMIT':commit, 'REPLACE_RUNNER_UUID':str(uuid4()),
            }.items():
                text = text.replace(old,new)
            config = ws.root / 'control.toml'
            for placeholder in ('WORKER_1_TO_4','CLAUDE_1_TO_2','CODEX_1_TO_2','AGY_1_TO_2'):
                text = text.replace('"REPLACE_' + placeholder + '"', '1')
            config.write_text(text)
            self.assertEqual(load('control', str(config))['profile_digest'], 'a'*64)
            (release/'prompts'/'worker.md').write_text('Uncommitted changed authority')
            with self.assertRaises(Problem):
                load('control', str(config))
