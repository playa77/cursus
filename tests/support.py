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
        'bearer_digest': __import__('hashlib').sha256(b'fixture-bearer').hexdigest(),
        'roles': {}, 'limits': {'repair_retries': 2, 'long_poll_seconds': 1},
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
    def __init__(self, control, path, local=True):
        self.control, self.path, self.local = control, path, local

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
        self.server = uvicorn.Server(uvicorn.Config(application(self.control, self.local),
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
