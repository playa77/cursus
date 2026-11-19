import asyncio
from importlib.resources import files
import unittest
from uuid import uuid4

from cursus.contracts import Problem
from tests.support import Database


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await Database().__aenter__()
        self.store = self.db.store

    async def asyncTearDown(self):
        await self.db.__aexit__()

    async def create(self, request_id=None, fail=False):
        async def apply(tx):
            identity = str(uuid4())
            await tx.save('phases', {'id': identity, 'state': 'intake'})
            cursor = await tx.event(identity, 'created', {'id': identity})
            if fail:
                raise ValueError('controlled rollback')
            return {'entity_id': identity, 'cursor': cursor}
        return await self.store.transact('operator', 'submit', request_id or str(uuid4()), {}, apply)

    async def test_commit_order_and_equal_replay(self):
        replies = await asyncio.gather(*(self.create() for _ in range(12)))
        self.assertEqual(sorted(r['cursor'] for r in replies), list(range(1, 13)))
        key = str(uuid4())
        first = await self.create(key)
        self.assertEqual(first, await self.create(key))
        self.assertEqual(len((await self.store.read('phases'))['items']), 13)

    async def test_rollback_and_digest_conflict(self):
        with self.assertRaises(ValueError):
            await self.create(fail=True)
        self.assertEqual((await self.store.read('phases'))['items'], [])
        key = str(uuid4())
        self.assertEqual((await self.create(key))['cursor'], 1)
        async def unused(tx):
            self.fail('conflicting callback ran')
        with self.assertRaises(Problem):
            await self.store.transact('operator', 'submit', key, {'changed': True}, unused)

    async def test_migration_integrity_and_wakeup(self):
        self.assertEqual(await self.store.migrate(), 1)
        raw = files('cursus').joinpath('migrations/001_initial.sql').read_bytes()
        with self.assertRaises(Problem):
            await self.store.migrate([('001_initial.sql', raw + b'\n-- changed')])
        waiter = asyncio.create_task(self.store.wait(__import__('time').monotonic() + 2, 0))
        await self.create()
        self.assertTrue(await waiter)
