"""Runner-owned Git and exact GitHub PR operations; never invoke repo code."""

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import shlex
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

from cursus.contracts import Problem, validate, _path


class GitHub:
    """Single-flight paced REST boundary; no automatic non-idempotent retry."""
    def __init__(self, credential_file):
        self.credential_file = credential_file
        self.last = 0.0
        self.blocked = False

    def request(self, method, path, body=None):
        from cursus.config import secret
        if self.blocked:
            raise Problem('github_unavailable', 'GitHub boundary is paused after denial or throttling.')
        time.sleep(max(0, self.last + 1 - time.monotonic()))
        self.last = time.monotonic()
        request = urllib.request.Request('https://api.github.com' + path,
            data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + secret(self.credential_file),
                     'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                     'X-GitHub-Api-Version': '2022-11-28'})
        # Redirects could forward publisher authority to another origin.
        from cursus.runner import NoRedirect
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                return json.loads(response.read(1048577))
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403,429):
                self.blocked = True
            # Do not retry this operation or bypass a Retry-After period. A
            # paused publisher requires operator diagnosis before reactivation.
            raise Problem('publication_unknown', 'GitHub rejected the operation; reconcile intent.') from None
        except (OSError, ValueError):
            raise Problem('publication_unknown', 'GitHub result is uncertain; reconcile intent.') from None


class Repository:
    def __init__(self, root, worktrees, reviews, enrollments, github, git='/usr/bin/git', credential_file=None):
        self.root, self.worktrees, self.reviews = map(Path, (root, worktrees, reviews))
        self.enrollments, self.github, self.binary = enrollments, github, git
        self.credential_file = credential_file
        self.worktree_admin = {}
        for path in (self.root, self.worktrees, self.reviews):
            path.mkdir(mode=0o711, parents=True, exist_ok=True)
        self.environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                            'GIT_TERMINAL_PROMPT': '0'}

    def git(self, directory, *args, data=None, allowed=(0,)):
        command = [self.binary, '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                   '-c', 'diff.external=', '-c', 'core.attributesFile=/dev/null',
                   '-c', 'user.name=Cursus', '-c', 'user.email=cursus@localhost',
                   '-c', 'commit.gpgsign=false', '-c', 'credential.helper=',
                   '-C', str(directory)]
        if self.credential_file:
            # Git's credential-store reads the operator's provisioned file
            # opaquely; credential values never enter argv or model context.
            command += ['-c', 'credential.helper=store --file=' + shlex.quote(str(self.credential_file))]
        if Path(directory) in self.worktree_admin:
            command += ['--git-dir=' + self.worktree_admin[Path(directory)], '--work-tree=' + str(directory)]
        result = subprocess.run([*command, *args], input=data, capture_output=True,
                                env=self.environment, timeout=120)
        if result.returncode not in allowed:
            raise Problem('git_failed', 'Git operation failed; no result is confirmed.')
        return result.stdout

    def enrolled(self, repo):
        validate('Repo', repo)
        key = (repo['owner'], repo['name'])
        item = self.enrollments.get(key)
        if item is None or repo['target_ref'] not in item['allowed_target_refs']:
            raise Problem('not_enrolled', 'Repository/target not enrolled on runner.')
        return item

    def cache(self, repo):
        item = self.enrolled(repo)
        token = sha256((repo['owner'] + '/' + repo['name']).encode()).hexdigest()
        path = self.root / (token + '.git')
        if not path.exists():
            path.mkdir(mode=0o700)
            self.git(path, 'init', '--bare', '--object-format=' + item.get('object_format', 'sha1'))
            remote = item.get('remote', f"https://github.com/{repo['owner']}/{repo['name']}.git")
            self.git(path, 'remote', 'add', 'origin', remote)
        return path

    def fetch(self, repo, ref=None):
        cache = self.cache(repo)
        self.git(cache, 'fetch', '--no-tags', '--no-recurse-submodules', 'origin', ref or repo['target_ref'])
        return self.git(cache, 'rev-parse', 'FETCH_HEAD').decode().strip()

    def workspace(self, repo, base, attempt_id):
        validate('Id', attempt_id)
        validate('Sha', base, object_format=self.enrolled(repo).get('object_format', 'sha1'))
        cache = self.cache(repo)
        path = self.worktrees / attempt_id
        if path.exists():
            raise Problem('state_conflict', 'Workspace already exists; do not relaunch.')
        self.git(cache, 'worktree', 'add', '--detach', str(path), base)
        self.worktree_admin[path] = (path / '.git').read_text().strip().removeprefix('gitdir: ')
        return path

    def snapshot(self, candidate, attempt_id, readonly=True):
        repo, head = candidate['repo'], candidate['head_sha']
        self.enrolled(repo)
        validate('Id', attempt_id)
        path = self.reviews / attempt_id
        path.mkdir(mode=0o700)
        raw = self.git(self.cache(repo), 'archive', '--format=tar', head)
        # No tarfile.extract: reject symlink/hardlink and path escapes before
        # writing any bytes. Review snapshots contain no .git or publisher data.
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive:
                name = member.name.rstrip('/')
                _path(name)
                if not (member.isfile() or member.isdir()) or '.git' in Path(name).parts:
                    raise Problem('unsafe_snapshot', 'Unsupported snapshot entry.')
                target = path / name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    target.chmod((0o555 if member.mode & 0o111 else 0o444) if readonly else
                                 (0o755 if member.mode & 0o111 else 0o644))
        if readonly:
            for directory in sorted((p for p in path.rglob('*') if p.is_dir()), reverse=True):
                directory.chmod(0o555)
            path.chmod(0o555)
        return path

    def ref(self, job, attempt_id, kind='candidate'):
        validate('Id', job['phase_id'])
        validate('Id', attempt_id)
        package = job.get('package_id', 'package')
        if not isinstance(package, str) or not package or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in package):
            raise Problem('invalid_ref', 'Unsafe package ID.')
        ref = f"refs/heads/wp/{job['phase_id']}/{package}/{attempt_id}/candidate"
        if kind == 'stage':
            ref = f"refs/heads/cursus-stage/{job['phase_id']}/{job.get('group_id', 'default')}/{attempt_id}"
        if job['input'].get('checkpoint_turn') is not None and kind == 'candidate':
            turn = job['input']['checkpoint_turn']
            validate('Seq',turn)
            ref = ref.removesuffix('candidate') + f'checkpoints/{turn}'
        return validate('Ref', ref)

    def remote_head(self, repo, ref):
        result = self.git(self.cache(repo), 'ls-remote', '--refs', 'origin', ref).decode().splitlines()
        if len(result) > 1:
            raise Problem('publication_mismatch', 'Unexpected remote refs.')
        return result[0].split()[0] if result else None

    def push(self, repo, ref, desired, expected, owned):
        self.enrolled(repo)
        validate('Ref', ref)
        validate('Sha', desired, object_format=self.enrolled(repo).get('object_format', 'sha1'))
        if ref != owned or ref in self.enrolled(repo)['allowed_target_refs']:
            raise Problem('forbidden', 'Ref is outside owned publication scope.')
        current = self.remote_head(repo, ref)
        if current == desired:
            return {'ref': ref, 'sha': desired}
        if current != expected:
            raise Problem('publication_mismatch', 'Remote head differs from expected head.')
        if expected is not None:
            validate('Sha', expected, object_format=self.enrolled(repo).get('object_format', 'sha1'))
            # The lease enforces the expected old SHA; history replacement is
            # independently forbidden, including when a caller supplies a lease.
            self.git(self.cache(repo), 'merge-base', '--is-ancestor', expected, desired)
        try:
            self.git(self.cache(repo), 'push', '--porcelain',
                     '--force-with-lease=' + ref + ':' + (expected or ''), 'origin', desired + ':' + ref)
        except Problem:
            if self.remote_head(repo, ref) != desired:
                raise Problem('publication_unknown', 'Ref write not confirmed.') from None
        if self.remote_head(repo, ref) != desired:
            raise Problem('publication_mismatch', 'Ref readback differs.')
        return {'ref': ref, 'sha': desired}

    def patch(self, candidate):
        return self.git(self.cache(candidate['repo']), 'diff', '--binary', '--no-ext-diff',
                        '--no-textconv', candidate['base_sha'], candidate['head_sha'])

    def capture(self, job, attempt_id, path, report):
        if not isinstance(report, dict) or not isinstance(report.get('summary'), str) or not report['summary'].strip():
            raise Problem('missing_report', 'Production requires a structured completion report.')
        repo, base = job['input']['repo'], job['input']['base_sha']
        ref = self.ref(job, attempt_id)
        existing = self.remote_head(repo, ref)
        if existing:
            if (self.git(path, 'rev-parse', 'HEAD').decode().strip() != existing
                    or self.git(path, 'status', '--porcelain')):
                raise Problem('publication_mismatch', 'Existing candidate differs from workspace.')
            return {'kind': 'code', 'repo': repo, 'base_sha': base, 'attempt_ref': ref, 'head_sha': existing}
        self.git(path, 'add', '--all')
        self.git(path, 'commit', '--allow-empty', '-m', 'Cursus candidate')
        head = self.git(path, 'rev-parse', 'HEAD').decode().strip()
        ref = self.ref(job, attempt_id)
        self.push(repo, ref, head, None, ref)
        return {'kind': 'code', 'repo': repo, 'base_sha': base, 'attempt_ref': ref, 'head_sha': head}

    def matching_pr(self, repo, ref, head):
        branch = ref.removeprefix('refs/heads/')
        base = repo['target_ref'].removeprefix('refs/heads/')
        query = urllib.parse.urlencode({'state': 'all', 'head': repo['owner'] + ':' + branch,
                                        'base': base, 'per_page': 100})
        items = self.github.request('GET', f"/repos/{repo['owner']}/{repo['name']}/pulls?{query}")
        if not isinstance(items, list) or len(items) >= 100:
            raise Problem('publication_unknown', 'PR lookup is incomplete.')
        matches = [item for item in items if item['head']['ref'] == branch and item['base']['ref'] == base
                   and item['head']['repo']['full_name'] == f"{repo['owner']}/{repo['name']}"
                   and item['base']['repo']['full_name'] == f"{repo['owner']}/{repo['name']}"]
        if len(matches) > 1:
            raise Problem('publication_mismatch', 'Multiple matching PRs.')
        if not matches:
            return None
        item = matches[0]
        if item['state'] != 'open' or item.get('merged_at') or item['head']['sha'] != head:
            raise Problem('publication_mismatch', 'PR is closed, merged or has a different head.')
        expected_url = f"https://github.com/{repo['owner']}/{repo['name']}/pull/{item['number']}"
        if item['html_url'] != expected_url or type(item['number']) is not int or item['number'] <= 0:
            raise Problem('publication_mismatch', 'PR identity is invalid.')
        return {'repo': repo, 'head_ref': ref, 'head_sha': head, 'number': item['number'], 'url': expected_url}

    def perform(self, job, attempt_id):
        step, data = job['step'], job['input']
        repo = data['repo']
        self.enrolled(repo)
        if step in ('resolve_input', 'inspect_target'):
            base = self.fetch(repo)
            result = {'base_sha': base}
            if step == 'resolve_input':
                source = data['source']
                if source['kind'] == 'inline':
                    result['text'] = source['text']
                else:
                    source_repo = dict(owner=source['owner'], name=source['name'], target_ref=repo['target_ref'])
                    self.fetch(source_repo, source['commit'])
                    _path(source['path'])
                    blob = source['commit'] + ':' + source['path']
                    length = int(self.git(self.cache(source_repo), 'cat-file', '-s', blob))
                    if length > 262144:
                        raise Problem('payload_too_large', 'Repository spec exceeds byte limit.')
                    raw = self.git(self.cache(source_repo), 'show', blob)
                    if len(raw) > 262144:
                        raise Problem('payload_too_large', 'Repository spec exceeds byte limit.')
                    result.update(text=raw.decode('utf-8'), source_commit=source['commit'])
            return result
        if step == 'stage_integration':
            candidate = data['candidate']
            path = self.workspace(repo, data['expected_head'], attempt_id)
            patch = self.patch(candidate)
            if patch:
                self.git(path, 'apply', '--index', '--binary', '-', data=patch)
            self.git(path, 'commit', '--allow-empty', '-m', 'Cursus integration')
            head = self.git(path, 'rev-parse', 'HEAD').decode().strip()
            ref = self.ref(job, attempt_id, 'stage')
            self.push(repo, ref, head, None, ref)
            staged = dict(candidate, base_sha=data['expected_head'], head_sha=head, attempt_ref=ref)
            return {'candidate': staged, 'patch_identity': sha256(self.patch(staged)).hexdigest(),
                    'candidate_patch_identity': sha256(patch).hexdigest()}
        if step in ('advance_integration', 'publish_pr', 'reconcile_publication'):
            intent = data['intent']
            if job.get('publication_id') != intent['id'] or intent['phase_id'] != job['phase_id'] or intent['repo'] != repo:
                raise Problem('forbidden', 'Publication intent identity mismatch.')
            ref, head = intent['head_ref'], intent['head_sha']
            owned = f"refs/heads/cursus/{job['phase_id']}/{job.get('group_id', 'default')}"
            if ref != owned:
                raise Problem('forbidden', 'Intent ref is outside owned lane.')
            if step == 'reconcile_publication':
                if intent['kind'] == 'advance_integration':
                    current = self.remote_head(repo,ref)
                    if current == head:
                        return {'kind':'confirmed','result':{'ref':ref,'sha':head}}
                    if current == intent['expected_old']:
                        return {'kind':'no_effect'}
                    raise Problem('publication_mismatch','Remote head differs from both expected outcomes.')
                if self.remote_head(repo,ref) != head or self.fetch(repo) != intent['target_sha']:
                    raise Problem('publication_mismatch','Read-only PR reconciliation found drift.')
                result = self.matching_pr(repo,ref,head)
                if result is None:
                    raise Problem('publication_unknown','PR absence does not prove an ambiguous request had no effect.')
                return {'kind':'confirmed','result':result}
            if step == 'advance_integration':
                return self.push(repo, ref, head, intent['expected_old'], owned)
            if self.remote_head(repo, ref) != head:
                raise Problem('publication_mismatch', 'Integration ref differs from verified head.')
            before = self.fetch(repo)
            if before != intent['target_sha']:
                raise Problem('target_drift', 'Target moved; publication is parked.')
            result = self.matching_pr(repo, ref, head)
            if result is None and step == 'publish_pr':
                self.github.request('POST', f"/repos/{repo['owner']}/{repo['name']}/pulls", {
                    'head': ref.removeprefix('refs/heads/'), 'base': repo['target_ref'].removeprefix('refs/heads/'),
                    'title': 'Cursus reviewed change', 'body': 'Verified head: ' + head})
                result = self.matching_pr(repo, ref, head)
            if result is None:
                raise Problem('publication_unknown', 'PR has not been confirmed.')
            if self.fetch(repo) != before or self.remote_head(repo, ref) != head:
                raise Problem('target_drift', 'Target/head changed during PR confirmation.')
            return result
        raise Problem('unsupported_milestone', 'Repository operation is unavailable.')
