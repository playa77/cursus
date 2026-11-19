"""Durable runner journal and bounded, runner-initiated HTTPS exchange."""

import asyncio
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, decode_json


class Journal:
    """Hash-chained, fsynced records protected by a lifetime exclusive lock.

    A partial final line was never acknowledged and can be truncated. Complete
    corrupt records cannot establish launch absence and fail closed.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = (self.root / 'lock').open('a+b')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise
        self.path = self.root / 'journal.jsonl'
        self.records, self.digest = [], '0' * 64
        raw = self.path.read_bytes() if self.path.exists() else b''
        offset = 0
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                with self.path.open('r+b') as output:
                    output.truncate(offset)
                    output.flush()
                    os.fsync(output.fileno())
                break
            try:
                item = decode_json(line)
                expected = sha256(self.digest.encode() + canonical_json(item['record'])).hexdigest()
                if item['digest'] != expected:
                    raise ValueError()
            except (ValueError, KeyError):
                self.close()
                raise Problem('journal_corrupt', 'Journal integrity is uncertain.') from None
            self.records.append(item['record'])
            self.digest = item['digest']
            offset += len(line)
        self.stream = self.path.open('ab', buffering=0)
        os.chmod(self.path, 0o600)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        generations = [r['value'] for r in self.records if r['kind'] == 'generation']
        self.generation = generations[0] if generations else str(uuid4())
        if not generations:
            self.record('generation', self.generation)

    def record(self, kind, value):
        record = {'kind': kind, 'value': value}
        digest = sha256(self.digest.encode() + canonical_json(record)).hexdigest()
        raw = canonical_json({'record': record, 'digest': digest}) + b'\n'
        self.stream.write(raw)
        os.fsync(self.stream.fileno())
        self.records.append(record)
        self.digest = digest
        return len(self.records)

    def close(self):
        if hasattr(self, 'stream'):
            self.stream.close()
        self.lock.close()


class HTTPS:
    def __init__(self, origin, bearer, generation):
        self.origin, self.bearer, self.generation = origin, bearer, generation
        if not origin.startswith('https://'):
            raise Problem('invalid_config', 'Runner requires HTTPS.')
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                                  NoRedirect())

    async def exchange(self, route, value, request_id, method='POST'):
        def send():
            url = self.origin + '/' + route
            if method == 'GET':
                url += '?' + urllib.parse.urlencode(value)
            request = urllib.request.Request(url, method=method,
                data=canonical_json(value) if method != 'GET' else None,
                headers={'Authorization': 'Bearer ' + self.bearer,
                         'X-Cursus-Generation': self.generation,
                         'Idempotency-Key': request_id, 'Content-Type': 'application/json'})
            try:
                with self.opener.open(request, timeout=35) as response:
                    return None if response.status == 204 else decode_json(response.read(1048577))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise Problem('unauthorized', 'Runner authorization denied.') from None
                raise Problem('transport', 'Runner request rejected.') from None
        return await asyncio.to_thread(send)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise Problem('transport', 'Runner redirects are forbidden.')


class Runner:
    def __init__(self, runner_id, journal, transport, repository=None, execution=None):
        self.id, self.journal, self.transport = runner_id, journal, transport
        self.repository, self.execution = repository, execution
        self.reconciled = False

    def record(self, kind, value):
        return self.journal.record(kind, value)

    async def exchange(self, route, value, request_id=None, method='POST'):
        return await self.transport.exchange(route, value, request_id or str(uuid4()), method)

    async def reconcile(self):
        retired = {r['value'] for r in self.journal.records if r['kind'] == 'retire'}
        pending = [r['value']['id'] for r in self.journal.records if r['kind'] == 'pending'
                   and r['value']['id'] not in retired]
        claims = [r['value'] for r in self.journal.records if r['kind'] == 'grant']
        observations = []
        for claim in claims:
            attempt_id = claim['attempt_id']
            launched = any(r['kind'] == 'launch' and r['value'] == attempt_id for r in self.journal.records)
            final = any(r['kind'] == 'event' and r['value']['attempt_id'] == attempt_id
                        and r['value']['kind'] == 'final' for r in self.journal.records)
            observations.append({'attempt_id': attempt_id,
                                 'kind': 'terminal_pending' if final else 'unknown' if launched else 'never_started',
                                 'reason': 'Durable journal observation.'})
        directive = await self.exchange(f'runners/{self.id}/reconcile', {
            'generation': self.journal.generation, 'observations': observations, 'pending_request_ids': pending})
        self.record('directive', directive)
        self.reconciled = directive['reconciled']
        return directive

    async def claim(self, slot, request_id=None):
        if not self.reconciled:
            raise Problem('state_conflict', 'Runner must reconcile first.')
        request_id = request_id or str(uuid4())
        self.record('pending', {'id': request_id, 'slot': slot})
        result = await self.exchange('jobs/next', {'slot': slot}, request_id, 'GET')
        if result:
            claim = result['claim']
            if claim['runner_id'] != self.id or claim['request_id'] != request_id:
                raise Problem('invalid_contract', 'Unexpected grant identity.')
            previous = [r['value'] for r in self.journal.records if r['kind'] == 'grant'
                        and r['value']['request_id'] == request_id]
            if previous and previous[0] != claim:
                raise Problem('state_conflict', 'Grant replay differs.')
            if not previous:
                self.record('grant', claim)
            return claim
        self.record('retire', request_id)
        return None

    async def serve(self):
        raise Problem('unsupported_milestone', 'Dispatch is not enabled yet.')


async def compose(settings):
    raise Problem('unsupported_milestone', 'Runner dispatch is not enabled yet.')
