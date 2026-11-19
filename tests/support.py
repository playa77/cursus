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
