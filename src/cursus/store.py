"""PostgreSQL ownership, ordered commits and immutable migration history.

The coordination lock is always acquired before any domain row. Callbacks do
only database/pure work: never hold the gate across filesystem or network I/O.
"""

import asyncio
from hashlib import sha256
from importlib.resources import files
import json
import time
from typing import Any
from cursus.contracts import Problem, canonical_json, validate


TABLES = frozenset(('phases', 'specs', 'plans', 'integration_lanes', 'packages',
                    'runners', 'jobs', 'attempts', 'commands', 'events',
                    'artifacts', 'publications'))


def encode(value):
    return canonical_json(value).decode()


def payload(row):
    return json.loads(row['payload']) if row is not None else None


class Transaction:
    """Control-owned callback interface under the single ordered gate."""

    def __init__(self, connection, cursor):
        self.connection = connection
        self.cursor = cursor

    async def get(self, table, identity):
        if table not in TABLES - {'events', 'specs', 'plans'}:
            raise ValueError('Unsupported entity table')
        return payload(await self.connection.fetchrow(
            f'SELECT payload FROM {table} WHERE id=$1', identity))

    async def save(self, table, value, **columns):
        if table not in TABLES - {'events', 'specs', 'plans'}:
            raise ValueError('Unsupported entity table')
        # Column names are internal literals, never input data.
        allowed = {'phase_id', 'group_id', 'plan_revision', 'package_id', 'owner',
                   'lane_id', 'step', 'scope', 'ordinal', 'slot', 'state',
                   'creation_cursor', 'job_id', 'runner_id', 'request_id', 'ack',
                   'status', 'attempt_id', 'issued_seq'}
        if columns.keys() - allowed:
            raise ValueError('Unsupported column')
        keys = ['id', 'payload', *columns]
        values = [value['id'], encode(value), *columns.values()]
        arguments = ','.join(f'${i}' for i in range(1, len(keys) + 1))
        assignments = ','.join(f'{key}=${index}' for index, key in enumerate(keys[1:], 2))
        updated = await self.connection.fetchval(
            f'UPDATE {table} SET {assignments} WHERE id=$1 RETURNING id', *values)
        if updated is None:
            await self.connection.execute(
                f"INSERT INTO {table} ({','.join(keys)}) VALUES ({arguments})", *values)

    async def revision(self, table, phase_id, revision, value):
        if table not in ('specs', 'plans'):
            raise ValueError('Unsupported revision')
        await self.connection.execute(
            f'INSERT INTO {table}(phase_id,revision,payload) VALUES($1,$2,$3)',
            phase_id, revision, encode(value))

    async def event(self, phase_id, kind, value, attempt_id=None, seq=None):
        self.cursor += 1
        await self.connection.execute(
            'INSERT INTO events(cursor,phase_id,attempt_id,source_seq,kind,digest,payload) '
            'VALUES($1,$2,$3,$4,$5,$6,$7)', self.cursor, phase_id, attempt_id,
            seq, kind, sha256(canonical_json(value)).hexdigest(), encode(value))
        return self.cursor


class Store:
    def __init__(self, pool):
        self.pool = pool
        # Waiters must not consume all connections needed by commands/readers.
        self.waiters = asyncio.Semaphore(max(1, pool.get_max_size() // 3))

    async def migrate(self, migrations=None):
        if migrations is None:
            root = files('cursus').joinpath('migrations')
            migrations = [(p.name, p.read_bytes()) for p in sorted(root.iterdir())
                          if p.name.endswith('.sql')]
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('SELECT pg_advisory_xact_lock(712938401)')
                await connection.execute('CREATE TABLE IF NOT EXISTS migration_history '
                                         '(version text PRIMARY KEY,digest text NOT NULL)')
                applied = dict(await connection.fetch('SELECT version,digest FROM migration_history'))
                if set(applied) - {name for name, _ in migrations}:
                    raise Problem('migration_mismatch', 'Unknown applied migration.')
                for name, raw in migrations:
                    digest = sha256(raw).hexdigest()
                    if name in applied:
                        if applied[name] != digest:
                            raise Problem('migration_mismatch', 'Applied SQL digest changed.')
                        continue
                    await connection.execute(raw.decode('utf-8'))
                    await connection.execute('INSERT INTO migration_history VALUES($1,$2)',
                                             name, digest)
        return len(migrations)

    async def transact(self, principal, route, request_id, value, transition):
        validate('Id', request_id)
        digest = sha256(canonical_json(value)).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                cursor = await connection.fetchval(
                    'SELECT cursor FROM coordination WHERE singleton FOR UPDATE')
                previous = await connection.fetchrow(
                    'SELECT digest,response FROM request_keys '
                    'WHERE principal=$1 AND route=$2 AND request_id=$3',
                    principal, route, request_id)
                if previous:
                    if previous['digest'] != digest:
                        raise Problem('idempotency_conflict', 'Request identity has different content.')
                    return json.loads(previous['response'])
                tx = Transaction(connection, cursor)
                response = await transition(tx)
                await connection.execute('UPDATE coordination SET cursor=$1', tx.cursor)
                if response is not None:
                    await connection.execute('INSERT INTO request_keys VALUES($1,$2,$3,$4,$5)',
                                             principal, route, request_id, digest, encode(response))
                await connection.execute("SELECT pg_notify('cursus_events',$1)", str(tx.cursor))
                return response

    async def read(self, table, identity=None, cursor=0):
        if table not in TABLES:
            raise ValueError('Unsupported query')
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation='repeatable_read', readonly=True):
                position = await connection.fetchval('SELECT cursor FROM coordination')
                if table == 'events':
                    rows = await connection.fetch(
                        'SELECT cursor,kind,time,attempt_id,payload FROM events WHERE cursor>$1 '
                        'AND ($2::uuid IS NULL OR phase_id=$2) ORDER BY cursor LIMIT 100',
                        cursor, identity)
                    floor = await connection.fetchval('SELECT event_floor FROM coordination')
                    return {'cursor': rows[-1]['cursor'] if rows else position,
                            'snapshot_cursor': position, 'floor': floor,
                            'reset': cursor < floor or cursor > position,
                            'items': [dict(cursor=row['cursor'], kind=row['kind'],
                                time=row['time'].isoformat(),
                                attempt_id=str(row['attempt_id']) if row['attempt_id'] else None,
                                payload=payload(row)) for row in rows]}
                if table in ('specs', 'plans'):
                    rows = await connection.fetch(f'SELECT payload FROM {table} WHERE phase_id=$1 '
                                                  'ORDER BY revision', identity)
                elif identity:
                    rows = await connection.fetch(f'SELECT payload FROM {table} WHERE id=$1', identity)
                else:
                    rows = await connection.fetch(f'SELECT payload FROM {table} LIMIT 100')
                return {'cursor': position, 'items': [payload(row) for row in rows]}

    async def browser_view(self, route, identity=None):
        """One committed snapshot for state, controls, logs and ready downloads."""
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation='repeatable_read', readonly=True):
                position = await connection.fetchval('SELECT cursor FROM coordination')
                entity = None
                if route in ('phases', 'attempts'):
                    entity = payload(await connection.fetchrow(
                        f'SELECT payload FROM {route} WHERE id=$1', identity))
                    if not entity:
                        raise Problem('not_found', 'Resource unavailable.')
                phase_id = (entity['claim']['job']['phase_id'] if route == 'attempts'
                            else identity if route == 'phases' else None)
                phase = (payload(await connection.fetchrow('SELECT payload FROM phases WHERE id=$1', phase_id))
                         if phase_id else None)
                counts = await connection.fetch("SELECT state,count(*) AS count FROM jobs GROUP BY state")
                tokens = await connection.fetchrow("SELECT sum((payload->'payload'->>'input_tokens')::bigint) AS input_tokens, "
                    "sum((payload->'payload'->>'output_tokens')::bigint) AS output_tokens FROM events WHERE kind='usage' "
                    "AND ($1::uuid IS NULL OR phase_id=$1) AND ($2::uuid IS NULL OR attempt_id=$2)",
                    phase_id, identity if route=='attempts' else None)
                costs = await connection.fetch("SELECT payload->'payload'->>'currency' AS currency, "
                    "sum((payload->'payload'->>'cost')::numeric)::text AS cost FROM events WHERE kind='usage' "
                    "AND payload->'payload' ? 'cost' AND ($1::uuid IS NULL OR phase_id=$1) "
                    "AND ($2::uuid IS NULL OR attempt_id=$2) GROUP BY payload->'payload'->>'currency'",
                    phase_id, identity if route=='attempts' else None)
                result = dict(cursor=position, entity=entity, phase=phase,
                              queue_counts={r['state']:r['count'] for r in counts},
                              usage=[{k:int(v) for k,v in dict(tokens).items() if v is not None},
                                     *[dict(r) for r in costs]])
                for table in ('phases', 'attempts', 'jobs', 'runners', 'artifacts'):
                    condition = ''
                    args = []
                    if phase_id and table in ('attempts', 'jobs'):
                        condition, args = ' WHERE phase_id=$1', [phase_id]
                    elif phase_id and table == 'artifacts':
                        condition, args = " WHERE payload->>'phase_id'=$1", [phase_id]
                    columns = 'payload,state' if table == 'jobs' else 'payload'
                    rows = await connection.fetch(f'SELECT {columns} FROM {table}{condition} ORDER BY id LIMIT 100', *args)
                    result[table] = [dict(payload(r), state=r['state']) if table == 'jobs' else payload(r) for r in rows]
                if phase_id:
                    rows = await connection.fetch('SELECT cursor,kind,time,attempt_id,payload FROM events '
                        'WHERE phase_id=$1 ORDER BY cursor DESC LIMIT 100', phase_id)
                    result['events'] = [dict(cursor=r['cursor'], kind=r['kind'], time=r['time'].isoformat(),
                        attempt_id=str(r['attempt_id']) if r['attempt_id'] else None, payload=payload(r))
                        for r in reversed(rows)]
                else:
                    result['events'] = []
                return result

    async def wait(self, deadline, cursor=None):
        async with self.waiters:
            return await self._wait(deadline,cursor)

    async def _wait(self, deadline, cursor=None):
        # Register before checking the cursor; notifications are advisory and a
        # bounded fallback still observes commits if a notification was missed.
        wake = asyncio.Event()
        async with self.pool.acquire() as connection:
            def notified(*_):
                wake.set()
            await connection.add_listener('cursus_events', notified)
            try:
                current = await connection.fetchval('SELECT cursor FROM coordination')
                if cursor is not None and current > cursor:
                    return True
                try:
                    await asyncio.wait_for(wake.wait(), max(0, min(5, deadline - time.monotonic())))
                    return True
                except TimeoutError:
                    return False
            finally:
                await connection.remove_listener('cursus_events', notified)
