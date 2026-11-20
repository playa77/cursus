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

    def test_serve_configuration_pins_the_role_release_and_rejects_unsafe_values(self):
        from cursus.config import load
        from tests.support import serve_config
        with workspace() as ws:
            path, release, commit, remote = serve_config(ws, 'postgresql://fixture')
            settings = load('serve', str(path))
            self.assertNotIn('profile_digest', settings)
            self.assertEqual(settings['repositories'][0]['name'], 'repo')
            self.assertEqual(settings['roles']['worker']['cli'], 'pi')
            (release / 'prompts' / 'worker.md').write_text('Uncommitted changed authority')
            with self.assertRaises(Problem):
                load('serve', str(path))
            # A committed role whose model could be read as a CLI option is refused at load.
            remote.git(release, 'checkout', '--', 'prompts')
            roles = (release / 'roles.toml').read_text()
            (release / 'roles.toml').write_text(roles.replace('model = "fixture"', 'model = "--evil"', 1))
            remote.git(release, 'add', '.')
            remote.git(release, 'commit', '-m', 'Unsafe model')
            path.write_text(path.read_text().replace(commit, remote.git(release, 'rev-parse', 'HEAD')))
            with self.assertRaises(Problem):
                load('serve', str(path))

    def test_unfilled_placeholders_are_named_before_any_other_validation(self):
        import tomllib
        from pathlib import Path
        from cursus.config import load
        from tests.support import serve_config, toml_text
        with self.assertRaises(Problem) as caught:
            load('serve', str(Path('deploy/cursus.example.toml').resolve()))
        self.assertIn('service.user', caught.exception.message)
        self.assertIn('more.', caught.exception.message)  # The list is bounded.
        with workspace() as ws:
            path, *_ = serve_config(ws, 'postgresql://fixture')
            value = tomllib.loads(path.read_text())
            value['capacity']['worker'] = 'REPLACE_WORKER_1_TO_4'
            value['repositories'][0]['owner'] = 'REPLACE_GITHUB_OWNER'
            path.write_text(toml_text(value))
            with self.assertRaises(Problem) as caught:
                load('serve', str(path))
            self.assertIn('Unfilled: capacity.worker, repositories[0].owner.', caught.exception.message)

    def test_serve_configuration_is_strict_and_single_process(self):
        import tomllib
        from cursus.config import load
        from tests.support import serve_config, toml_text
        with workspace() as ws:
            path, *_ = serve_config(ws, 'postgresql://fixture')
            good = tomllib.loads(path.read_text())
            load('serve', str(path))
            def variant(change):
                value = tomllib.loads(path.read_text())
                change(value)
                other = ws.root / 'variant.toml'
                other.write_text(toml_text(value))
                return str(other)
            for kind in ('control', 'runner'):
                with self.assertRaises(Problem):
                    load(kind, str(path))  # The two-process kinds no longer exist.
            for change in (lambda v: v.update(schema_version=2),
                           lambda v: v['service'].update(bearer_file='/x'),   # No runner bearer exists.
                           lambda v: v['service'].update(origin='https://x.example'),
                           lambda v: v['service'].update(listen_host='0.0.0.0'),
                           lambda v: v['runner'].update(bearer_digest_file='/x'),
                           lambda v: v['limits'].update(long_poll_seconds=30),
                           lambda v: v.pop('execution'),
                           lambda v: v['capacity'].update(worker=9)):
                with self.assertRaises(Problem):
                    load('serve', variant(change))
