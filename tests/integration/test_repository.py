import unittest
from uuid import uuid4
from cursus.contracts import Problem
from tests.support import workspace, GitRemote, code_input


class RepositoryTests(unittest.TestCase):
    def test_git_candidate_and_conditional_publication(self):
        with workspace() as ws:
            remote = GitRemote(ws.root)
            repo = remote.repository(ws)
            target = code_input()['repo']
            resolved = repo.perform({'step': 'resolve_input', 'input': {'repo': target,
                'source': {'kind': 'repo', 'owner': 'fixture', 'name': 'repo',
                           'commit': remote.base, 'path': 'spec.md'}}}, str(uuid4()))
            self.assertEqual(resolved['source_commit'], remote.base)
            phase, attempt = str(uuid4()), str(uuid4())
            job = {'phase_id': phase, 'package_id': 'one', 'step': 'produce',
                   'input': {'repo': target, 'base_sha': remote.base}}
            path = repo.workspace(target, remote.base, attempt)
            (path / 'result.txt').write_text('done')
            candidate = repo.capture(job, attempt, path, {'summary': 'Implemented.'})
            self.assertEqual(repo.remote_head(target, candidate['attempt_ref']), candidate['head_sha'])
            staged = repo.perform({'phase_id': phase, 'step': 'stage_integration',
                'input': {'repo': target, 'candidate': candidate, 'expected_head': remote.base}}, str(uuid4()))
            head = staged['candidate']['head_sha']
            ref = f'refs/heads/cursus/{phase}/default'
            self.assertEqual(repo.push(target, ref, head, None, ref), repo.push(target, ref, head, None, ref))
            with self.assertRaises(Problem):
                repo.push(target, 'refs/heads/main', head, remote.base, 'refs/heads/main')
            with self.assertRaises(Problem):
                repo.push(target, ref, remote.base, None, ref)
            snapshot = repo.snapshot(candidate, str(uuid4()))
            self.assertEqual((snapshot / 'result.txt').read_text(), 'done')
            self.assertFalse((snapshot / '.git').exists())
            self.assertEqual(remote.git(remote.remote, 'rev-parse', 'main'), remote.base)

    def test_exact_pr_lookup_and_closed_refusal(self):
        with workspace() as ws:
            remote = GitRemote(ws.root)
            repo = remote.repository(ws)
            target = code_input()['repo']
            phase = str(uuid4())
            repo.fetch(target)
            ref = f'refs/heads/cursus/{phase}/default'
            repo.push(target, ref, remote.base, None, ref)
            self.assertIsNone(repo.matching_pr(target, ref, remote.base))
            remote.request('POST', '/repos/fixture/repo/pulls', {'head': ref[11:], 'base': 'main',
                                                             'title': 'Test', 'body': 'Test'})
            first = repo.matching_pr(target, ref, remote.base)
            self.assertEqual(first, repo.matching_pr(target, ref, remote.base))
            remote.prs[0]['state'] = 'closed'
            with self.assertRaises(Problem):
                repo.matching_pr(target, ref, remote.base)
            self.assertEqual(len(remote.prs), 1)
