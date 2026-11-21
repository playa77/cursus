"""Disposable workspaces; later packages add external boundary fixtures here."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Iterator


@dataclass(frozen=True)
class Workspace:
    root: Path
    state: Path
    artifacts: Path
    worktrees: Path


@contextmanager
def workspace() -> Iterator[Workspace]:
    """Create only empty isolated directories, never synthetic Cursus state."""
    with TemporaryDirectory(prefix="cursus test — ") as directory:
        root = Path(directory)
        paths = [root / name for name in ("state", "artifacts", "worktrees")]
        for path in paths:
            path.mkdir(mode=0o700)
        yield Workspace(root, *paths)


class Database:
    """Empty isolated schema on an operator-authorized disposable PostgreSQL.

    CURSUS_TEST_DSN must identify test storage, never a production database.
    The fixture drops only its own random schema; no state rows are seeded.
    """

    async def __aenter__(self):
        import os
        import asyncpg
        from uuid import uuid4
        from cursus.store import Store
        dsn = os.environ.get('CURSUS_TEST_DSN')
        if not dsn:
            raise RuntimeError('Set CURSUS_TEST_DSN to a disposable PostgreSQL instance.')
        self.schema = 'cursus_test_' + uuid4().hex
        self.admin = await asyncpg.connect(dsn)
        await self.admin.execute(f'CREATE SCHEMA {self.schema}')
        self.pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=8, server_settings={'search_path': self.schema})
        self.store = Store(self.pool)
        await self.store.migrate()
        return self

    async def __aexit__(self, *_):
        await self.pool.close()
        await self.admin.execute(f'DROP SCHEMA {self.schema} CASCADE')
        await self.admin.close()


def settings():
    """Non-secret local enrollment and no activated model roles."""
    from uuid import uuid4
    return {
        'service': {'role_release_commit': '0' * 40},
        'runner': {'id': str(uuid4())},
        'capacity': {'worker': 4, 'claude': 2, 'codex': 2, 'agy': 2, 'verifier': 1, 'repository': 1},
        'roles': {}, 'limits': {'repair_retries': 2},
        'repositories': [{'owner': 'fixture', 'name': 'repo', 'object_format': 'sha1',
                          'allowed_target_refs': ['refs/heads/main'],
                          'checks': [{'id': 'unit', 'argv': ['/usr/bin/true'],
                                      'cwd': '.', 'timeout_seconds': 5}],
                          'phase_check_ids': ['unit']}],
    }


def code_input():
    return {'workflow': 'code', 'form': 'one-shot',
            'source': {'kind': 'inline', 'text': 'Implement the assigned change.'},
            'repo': {'owner': 'fixture', 'name': 'repo', 'target_ref': 'refs/heads/main'},
            'plan_debate': False, 'spec_debate': False}


class SocketService:
    """Real HTTP over a private disposable Unix socket; no ASGI test shortcut."""
    def __init__(self, control, path, local=True, browser=False):
        self.control, self.path, self.local = control, path, local
        self.browser = browser

    async def __aenter__(self):
        import asyncio
        import socket
        import uvicorn
        from cursus.http import application
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        self.path.chmod(0o600)
        self.socket.listen(128)
        self.socket.setblocking(False)
        self.server = uvicorn.Server(uvicorn.Config(application(self.control, self.local, self.browser),
                                                    log_level='error', lifespan='off'))
        self.task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
        for _ in range(100):
            if self.server.started:
                return self
            if self.task.done():
                await self.task
            await asyncio.sleep(.01)
        raise RuntimeError('Test service startup deadline exceeded')

    async def __aexit__(self, *_):
        self.server.should_exit = True
        await self.task
        self.socket.close()
        self.path.unlink(missing_ok=True)


class GitRemote:
    """A trusted bare remote plus a request-contract GitHub fixture."""
    def __init__(self, root):
        import subprocess
        import os
        self.root = root
        self.remote = root / 'remote.git'
        self.seed = root / 'seed'
        self.prs, self.requests = [], []
        self.environment = {'PATH': '/usr/bin:/bin', 'GIT_CONFIG_NOSYSTEM': '1',
                            'GIT_CONFIG_GLOBAL': '/dev/null', 'LANG': 'C.UTF-8'}
        def git(path, *args):
            return subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
                                   '-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost',
                                   '-C', str(path), *args], env=self.environment,
                                  capture_output=True, check=True).stdout.decode().strip()
        self.git = git
        self.remote.mkdir()
        git(self.remote, 'init', '--bare', '--initial-branch=main')
        self.seed.mkdir()
        git(self.seed, 'init', '--initial-branch=main')
        (self.seed / 'spec.md').write_text('Make the requested change.')
        (self.seed / 'check.py').write_text('from pathlib import Path\nassert Path("result.txt").read_text() == "done"\n')
        git(self.seed, 'add', '.')
        git(self.seed, 'commit', '-m', 'Initial')
        self.base = git(self.seed, 'rev-parse', 'HEAD')
        git(self.seed, 'remote', 'add', 'origin', str(self.remote))
        git(self.seed, 'push', 'origin', 'main')

    def request(self, method, path, body=None):
        from urllib.parse import urlsplit, parse_qs
        from cursus.contracts import Problem
        self.requests.append((method, path, body))
        if not path.startswith('/repos/fixture/repo/pulls'):
            raise AssertionError('Unauthorized REST endpoint')
        if method == 'GET':
            return self.prs.copy()
        if method != 'POST' or set(body) != {'head', 'base', 'title', 'body'}:
            raise AssertionError('Unauthorized REST operation')
        head = self.git(self.remote, 'rev-parse', 'refs/heads/' + body['head'])
        number = len(self.prs) + 1
        item = {'number': number, 'html_url': f'https://github.com/fixture/repo/pull/{number}',
                'state': 'open', 'merged_at': None,
                'head': {'ref': body['head'], 'sha': head, 'repo': {'full_name': 'fixture/repo'}},
                'base': {'ref': body['base'], 'repo': {'full_name': 'fixture/repo'}}}
        self.prs.append(item)
        return item

    def repository(self, ws):
        from cursus.repository import Repository
        enrollment = {('fixture', 'repo'): {'remote': str(self.remote), 'object_format': 'sha1',
                                          'allowed_target_refs': ['refs/heads/main']}}
        return Repository(ws.root / 'cache', ws.worktrees, ws.root / 'reviews', enrollment, self)


def toml_text(value):
    """Minimal TOML writer for test configuration (strings, ints, bools, lists, tables)."""
    import json
    lines = []

    def scalar(item):
        if isinstance(item, bool):
            return 'true' if item else 'false'
        if isinstance(item, list):
            return '[' + ', '.join(scalar(i) for i in item) + ']'
        return json.dumps(item)

    def is_tables(item):
        return isinstance(item, list) and bool(item) and all(isinstance(i, dict) for i in item)

    def emit(name, table, array=False):
        if name:
            lines.append(('[[%s]]' if array else '[%s]') % name)
        for key, item in table.items():
            if not isinstance(item, dict) and not is_tables(item):
                lines.append(f'{key} = {scalar(item)}')
        for key, item in table.items():
            if isinstance(item, dict):
                emit(f'{name}.{key}' if name else key, item)
            elif is_tables(item):
                for entry in item:
                    emit(f'{name}.{key}' if name else key, entry, True)

    emit('', value)
    return '\n'.join(lines) + '\n'


def serve_config(ws, dsn, clis=None):
    """A real, loadable single-process config built from the public example template.

    Returns (path, release_dir, release_commit, remote). Roles come from a committed
    role release; the fixture remote is a local bare repository (set `remote` on the
    loaded enrollment, which the production loader does not accept).
    """
    import grp
    import os
    import pwd
    import shutil
    import sys
    import tomllib
    from uuid import uuid4
    remote = GitRemote(ws.root)
    release = ws.root / 'release'  # Separate from the fixture remote's content.
    release.mkdir()
    remote.git(release, 'init', '--initial-branch=main')
    role_text = Path('roles.toml').read_text()
    for old, new in {'REPLACE_QUALIFIED_MODEL': 'fixture', 'REPLACE_QUALIFIED_REASONING': 'fixture',
                     'REPLACE_QUALIFIED_OPENCODE_GO_PROVIDER_ID': 'fixture-go'}.items():
        role_text = role_text.replace(old, new)
    (release / 'roles.toml').write_text(role_text)
    shutil.copytree('prompts', release / 'prompts')
    remote.git(release, 'add', '.')
    remote.git(release, 'commit', '-m', 'Fixture role release')
    commit = remote.git(release, 'rev-parse', 'HEAD')
    dsn_file = ws.root / 'dsn'
    dsn_file.write_text(dsn)
    dsn_file.chmod(0o600)
    config = tomllib.loads(Path('deploy/cursus.example.toml').read_text())
    service = config['service']
    service.update(user=pwd.getpwuid(os.getuid()).pw_name, operator_group=grp.getgrgid(os.getgid()).gr_name,
                   operator_socket=str(ws.root / 'operator.sock'), listen_port=0, dsn_file=str(dsn_file),
                   artifact_root=str(ws.artifacts), roles_file=str(release / 'roles.toml'),
                   prompts_root=str(release / 'prompts'), role_release_commit=commit,
                   operator_login='fixture', external_origin='https://fixture.example.ts.net',
                   state_root=str(ws.state), repository_root=str(ws.root / 'cache'),
                   worktree_root=str(ws.worktrees), review_root=str(ws.root / 'reviews'))
    config['runner']['id'] = str(uuid4())
    config['publisher'].update(git_credential_file=str(ws.root / 'git-credential'),
                               github_credential_file=str(ws.root / 'github-credential'))
    config['capacity'].update(worker=2, claude=1, codex=1, agy=1)
    config['execution'] = dict(disk_reserve_mb=1, host_reserve_mb=1)
    if clis:
        config['execution']['clis'] = dict(clis)
    config['repositories'] = [{'owner': 'fixture', 'name': 'repo', 'object_format': 'sha1',
        'allowed_target_refs': ['refs/heads/main'], 'phase_check_ids': ['unit'],
        'checks': [{'id': 'unit', 'argv': [sys.executable, 'check.py'], 'cwd': '.', 'timeout_seconds': 10}]}]
    path = ws.root / 'cursus.toml'
    path.write_text(toml_text(config))
    return path, release, commit, remote


def json_quote(value):
    import json
    return json.dumps(value)
