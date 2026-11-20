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
import urllib.parse
import pwd
import random
import time
import shutil
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, decode_json, validate


class Journal:
    """Hash-chained, fsynced records protected by a lifetime exclusive lock.

    A partial final line was never acknowledged and can be truncated. Complete
    corrupt records cannot establish launch absence and fail closed.
    """
    def __init__(self, root, max_bytes=2147483648):
        self.max_bytes = max_bytes
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
        offset = 0
        source = self.path.open('rb') if self.path.exists() else []
        for line in source:
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
                if hasattr(source, 'close'):
                    source.close()
                self.close()
                raise Problem('journal_corrupt', 'Journal integrity is uncertain.') from None
            self.records.append(item['record'])
            self.digest = item['digest']
            offset += len(line)
        if hasattr(source, 'close'):
            source.close()
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
        terminal = kind in ('ack','retire','directive') or (kind == 'event' and value.get('kind') == 'final')
        reserve = 0 if terminal else 65536
        if self.path.stat().st_size + len(raw) + reserve > self.max_bytes or shutil.disk_usage(self.root).free < len(raw) + reserve:
            raise Problem('storage', 'Journal reserve exhausted; intake is stopped.')
        remaining = memoryview(raw)
        while remaining:
            written = self.stream.write(remaining)
            if not written:
                raise OSError('Journal write did not complete')
            remaining = remaining[written:]
        os.fsync(self.stream.fileno())
        self.records.append(record)
        self.digest = digest
        result = len(self.records)
        if kind == 'retire' and getattr(self, 'compaction', False):
            self.compact()
        return result

    def compact(self):
        # Completed request history has no recovery authority. Keep unresolved
        # attempts intact, including launch intent and unacknowledged finals.
        retired = {r['value'] for r in self.records if r['kind'] == 'retire'}
        grants = {r['value']['attempt_id']:r['value'] for r in self.records if r['kind']=='grant'}
        removed = {a for a,c in grants.items() if c['request_id'] in retired}
        files = {r['value']['file']['id'] for r in self.records if r['kind']=='artifact_pending' and r['value']['attempt_id'] in removed}
        directives = [r for r in self.records if r['kind']=='directive']
        cleaned = {r['value'] for r in self.records if r['kind']=='workspace_cleaned'}
        keep = []
        for record in self.records:
            if record['kind'] in ('workspace_cleanup','workspace_cleaned') and (record['value'].get('attempt') if isinstance(record['value'],dict) else record['value']) in cleaned:
                continue
            kind, value = record['kind'], record['value']
            if kind == 'retire' or kind == 'pending' and value['id'] in retired:
                continue
            if kind == 'directive' and record is not directives[-1]:
                continue
            if kind in ('launch','stale_stop','container_removed') and value in removed:
                continue
            if isinstance(value,dict) and (value.get('attempt_id') in removed or kind in ('container_intent','container_identity') and value.get('attempt') in removed or kind == 'artifact_receipt' and value.get('id') in files or kind == 'artifact_discarded' and value.get('id') in files):
                continue
            keep.append(record)
        temporary = self.root / 'journal.compact'
        digest = '0' * 64
        with temporary.open('wb') as output:
            os.chmod(temporary, 0o600)
            for record in keep:
                digest = sha256(digest.encode() + canonical_json(record)).hexdigest()
                output.write(canonical_json({'record':record,'digest':digest}) + b'\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.stream.close()
        self.stream = self.path.open('ab', buffering=0)
        self.records, self.digest = keep, digest
        for file_id in files:
            validate('Id', file_id)
            (self.root / ('evidence-' + file_id)).unlink(missing_ok=True)

    def close(self):
        if hasattr(self, 'stream'):
            self.stream.close()
        self.lock.close()


class HTTPS:
    def __init__(self, origin, bearer, generation):
        self.origin, self.bearer, self.generation = origin, bearer, generation
        if not origin.startswith('https://'):
            raise Problem('invalid_config', 'Runner requires HTTPS.')
        self.capacity = asyncio.Semaphore(2)
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
        async with self.capacity:
            return await asyncio.to_thread(send)

    async def upload(self, attempt_id, ref, path):
        from cursus.runner_files import headers, checked_bytes
        raw = checked_bytes(ref, path.read_bytes())
        return await self.binary(f'attempts/{attempt_id}/artifacts/{ref["id"]}', raw, headers(ref))

    async def download(self, ref, claim_id):
        from cursus.runner_files import checked_bytes
        raw = await self.binary(f'runner/artifacts/{ref["id"]}?claim_id={claim_id}')
        return checked_bytes(ref, raw)

    async def binary(self, route, raw=None, extra=None):
        def send():
            headers = {'Authorization': 'Bearer ' + self.bearer,
                       'X-Cursus-Generation': self.generation, 'Idempotency-Key': str(uuid4())}
            headers.update(extra or {})
            request = urllib.request.Request(self.origin + '/' + route, data=raw,
                method='PUT' if raw is not None else 'GET', headers=headers)
            try:
                with self.opener.open(request, timeout=35) as response:
                    value = response.read(32 * 1024 * 1024 + 1)
                    return decode_json(value) if raw is not None else value
            except urllib.error.HTTPError as exc:
                raise Problem('unauthorized' if exc.code in (401,403) else 'transport',
                              'Artifact transfer rejected.') from None
        async with self.capacity:
            return await asyncio.to_thread(send)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise Problem('transport', 'Runner redirects are forbidden.')


class Runner:
    def __init__(self, runner_id, journal, transport, repository=None, execution=None):
        self.id, self.journal, self.transport = runner_id, journal, transport
        self.repository, self.execution = repository, execution
        self.reconciled = False
        self.activation = str(uuid4())
        self.active = {}
        self.command_queues = {}
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.replay_lock = asyncio.Lock()
        self.tasks = set()
        self.pending_claims = {}
        self.pending_status = {}
        self.runtime = getattr(execution, 'runtime', None)
        journal.compaction = self.runtime is not None
        self.capacities = self.runtime.capacity if self.runtime else dict(worker=2, verifier=1, frontier=1, repository=1)
        self.recovered_stops = {r['value'] for r in journal.records if r['kind']=='container_removed'}
        if self.runtime:
            self.runtime.record = self.record
            identities = {r['value']['attempt']:r['value'] for r in journal.records if r['kind'] in ('container_intent','container_identity')}
            for attempt, item in identities.items():
                if attempt not in self.recovered_stops and attempt not in self.runtime.entries:
                    self.runtime.entries[attempt] = dict(item)
            self.runtime.save()
        self.poll_rotation = 0
        self.next_cleanup = 0

    def record(self, kind, value):
        return self.journal.record(kind, value)

    async def exchange(self, route, value, request_id=None, method='POST'):
        return await self.transport.exchange(route, value, request_id or str(uuid4()), method)

    async def reconcile(self):
        if self.runtime:
            outcomes = await self.runtime.recover()
            self.recovered_stops.update(a for a, stopped in outcomes.items() if stopped)
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
            unknown_final = max((r['value']['seq'] for r in self.journal.records if r['kind']=='event' and r['value']['attempt_id']==attempt_id and r['value']['kind']=='final' and r['value']['payload']['kind']=='unknown'), default=0)
            acknowledged = max((r['value']['committed_through'] for r in self.journal.records if r['kind']=='ack' and r['value']['attempt_id']==attempt_id), default=0)
            if unknown_final and acknowledged >= unknown_final:
                final = False
            starts = [r['value'] for r in self.journal.records if r['kind']=='process_context' and r['value']['attempt_id']==attempt_id]
            stopped = attempt_id in self.recovered_stops or (not self.runtime and starts and starts[-1]['boot_id'] != self.boot_id)
            observations.append({'attempt_id': attempt_id,
                                 'kind': 'live' if attempt_id in self.active else 'stopped' if stopped and not final else 'terminal_pending' if final else 'unknown' if launched else 'never_started',
                                 'reason': 'Durable journal observation.'})
        directive = await self.exchange(f'runners/{self.id}/reconcile', {
            'generation': self.journal.generation, 'observations': observations, 'pending_request_ids': pending, **({'capacity': self.capacities} if self.runtime else {})})
        for attempt_id,disposition in directive['dispositions'].items():
            if disposition=='stop-stale' and attempt_id in self.command_queues:
                prior=any(r['kind']=='stale_stop' and r['value']==attempt_id for r in self.journal.records)
                if not prior:
                    self.record('stale_stop',attempt_id)
                    await self.command_queues[attempt_id].put({'id':str(uuid4()),'attempt_id':attempt_id,'action':'stop'})
        held_ids = {c['attempt_id'] for c in directive['held_claims']}
        resolved = {r['value']['payload']['command_id'] for r in self.journal.records
                    if r['kind']=='event' and r['value']['kind']=='command_result'}
        for record in list(self.journal.records):
            if record['kind']=='command_intent':
                command = record['value']
                if command['id'] not in resolved and command['attempt_id'] in held_ids and command['attempt_id'] not in self.active:
                    await self.event(command['attempt_id'],'command_result',
                        {'command_id':command['id'],'disposition':'uncertain','reason':'Prior RPC delivery has no durable result.'})
                    resolved.add(command['id'])
        self.record('directive', directive)
        if self.runtime:
            for attempt_id, disposition in directive['dispositions'].items():
                if disposition in ('ignore-stale','stop-stale'):
                    self.pending_claims.pop(attempt_id, None)
                    self.pending_status.pop(attempt_id, None)
                if disposition == 'ignore-stale' and attempt_id not in self.runtime.entries and attempt_id not in self.active:
                    grant = next((r['value'] for r in self.journal.records if r['kind']=='grant' and r['value']['attempt_id']==attempt_id), None)
                    if grant:
                        self.record('workspace_cleanup',dict(attempt=attempt_id,since=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
                        self.record('retire', grant['request_id'])
        self.reconciled = directive['reconciled']
        return directive

    async def claim(self, slot, request_id=None):
        if not self.reconciled:
            raise Problem('state_conflict', 'Runner must reconcile first.')
        request_id = request_id or str(uuid4())
        self.record('pending', {'id': request_id, 'slot': slot})
        result = await self.exchange('jobs/next', {'slot': slot}, request_id, 'GET')
        if result:
            claim = validate('Claim', result['claim'])
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

    async def event(self, attempt_id, kind, payload):
        seq = 1 + sum(r['kind'] == 'event' and r['value']['attempt_id'] == attempt_id
                      for r in self.journal.records)
        event = {'attempt_id': attempt_id, 'seq': seq, 'kind': kind, 'payload': payload}
        self.record('event', event)
        return event

    async def replay(self):
        async with self.replay_lock:
            await self._replay()

    async def _replay(self):
        from cursus.runner_files import replay
        await replay(self)
        positions = {}
        for record in self.journal.records:
            if record['kind'] == 'ack':
                positions[record['value']['attempt_id']] = record['value']['committed_through']
        grouped = {}
        for record in self.journal.records:
            if record['kind'] == 'event':
                event = record['value']
                if event['seq'] > positions.get(event['attempt_id'], 0):
                    grouped.setdefault(event['attempt_id'], []).append(event)
        for attempt_id, events in list(grouped.items())[:16]:
            for offset in range(0, min(len(events), 100), 100):
                ack = await self.exchange(f'attempts/{attempt_id}/events', events[offset:offset + 100])
                self.record('ack', dict(ack, attempt_id=attempt_id))
        # Retire only after both the final receipt and independent runtime
        # cleanup. This also catches preparation failures cleaned after replay.
        positions = {r['value']['attempt_id']:r['value']['committed_through'] for r in self.journal.records if r['kind']=='ack'}
        for record in list(self.journal.records):
            if record['kind'] != 'event' or record['value']['kind'] != 'final':
                continue
            final = record['value']
            attempt_id = final['attempt_id']
            if final['payload']['kind'] == 'unknown' or positions.get(attempt_id,0) < final['seq'] or self.runtime and attempt_id in self.runtime.entries:
                continue
            grant = next((r['value'] for r in self.journal.records if r['kind']=='grant' and r['value']['attempt_id']==attempt_id), None)
            if grant and self.runtime and not any(r['kind']=='workspace_cleanup' and r['value']['attempt']==attempt_id for r in self.journal.records):
                self.record('workspace_cleanup',dict(attempt=attempt_id,since=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
            if grant and not any(r['kind']=='retire' and r['value']==grant['request_id'] for r in self.journal.records):
                self.record('retire',grant['request_id'])

    def assign(self, path, configured, readonly=False):
        if self.runtime or not configured or os.geteuid() != 0:
            return
        user = pwd.getpwnam(configured['user'])
        # Never traverse symlinks while preparing the privilege boundary.
        if not readonly:
            for entry in [path, *path.rglob('*')]:
                if entry.name == '.git' or entry.is_symlink():
                    continue
                os.chown(entry, user.pw_uid, user.pw_gid, follow_symlinks=False)
        path.chmod(0o555 if readonly else 0o700)

    def progress(self, event, job, attempt_id, outcome=None):
        import logging
        from datetime import datetime, timezone
        from cursus import __version__
        logging.getLogger('cursus.runner').info(json.dumps({
            'time': datetime.now(timezone.utc).isoformat(), 'service': 'runner',
            'version': __version__, 'event': event, 'job_id': job['id'],
            'attempt_id': attempt_id, 'step': job['step'], 'outcome': outcome}))

    async def dispatch(self, claim):
        attempt = claim['attempt_id']
        if self.runtime and (len(self.storage_pending()) >= 32 or any(shutil.disk_usage(path).free < self.runtime.settings['disk_reserve_mb'] * 1024 * 1024 for path in (self.repository.root,self.repository.worktrees,self.repository.reviews))):
            self.pending_claims[attempt] = claim
            self.pending_status.setdefault(attempt, dict(attempt=attempt,lane=claim['job']['slot'],state='waiting',since=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),reason='Storage reserve or cleanup backlog blocks admission; automatic retry.'))
            self.active.pop(attempt,None)
            return None
        execution_job = claim['job']['step'] in ('produce','debug','verify','review','plan','scout','interview','debate')
        if self.runtime and execution_job and attempt not in self.runtime.entries:
            role = claim['job'].get('invocation', {}).get('role', {})
            lane = 'verifier' if claim['job']['step'] == 'verify' else 'worker' if role['cli'] == 'pi' else role['cli']
            if not await self.runtime.reserve(attempt, lane, role.get('cli')):
                self.pending_claims[attempt] = claim
                self.pending_status.setdefault(attempt, dict(attempt=attempt,lane=lane,state='waiting',since=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),reason='Waiting for resource/credential capacity; verifier reserve is protected. Automatic retry.'))
                self.active.pop(attempt, None)
                return None
        self.pending_status.pop(attempt,None)
        try:
            return await self._dispatch(claim)
        finally:
            if self.runtime and attempt in self.runtime.entries:
                await asyncio.shield(self.runtime.cleanup(attempt))
                self.runtime.owned.discard(attempt)
            self.active.pop(attempt, None)
            self.command_queues.pop(attempt, None)

    async def _dispatch(self, claim):
        job, attempt_id = claim['job'], claim['attempt_id']
        if any(r['kind'] == 'launch' and r['value'] == attempt_id for r in self.journal.records):
            raise Problem('state_conflict', 'Launch intent exists; automatic relaunch forbidden.')
        self.record('process_context', {'attempt_id':attempt_id,'boot_id':self.boot_id,'activation':self.activation})
        self.record('launch', attempt_id)
        self.active[attempt_id] = job['slot']
        self.command_queues[attempt_id] = asyncio.Queue()
        self.progress('started', job, attempt_id)
        await self.event(attempt_id, 'started', {'service_activation': self.activation,
                                              'time': __import__('datetime').datetime.now(
                                                  __import__('datetime').timezone.utc).isoformat()})
        async def log(payload):
            # Agent text is sanitized by Execution before reaching persistence.
            await self.event(attempt_id, 'log', payload)
        async def lifecycle(pid):
            if self.runtime:
                return  # Container identity is the execution boundary, not this transport PID.
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            self.record('process',{'attempt_id':attempt_id,'pid':pid,'start_ticks':stat[19],
                'boot_id':self.boot_id,'activation':self.activation})
        async def command_result(value):
            await self.event(attempt_id,'command_result',value)
        try:
            step = job['step']
            if step in ('produce','debug'):
                data = job['input']
                path = await asyncio.to_thread(self.repository.workspace, data['repo'], data['base_sha'], attempt_id)
                configured = self.execution.configured(job['invocation'])
                self.assign(path, configured)
                if step == 'debug':
                    async def checkpoint(turn, report):
                        checkpoint_job = dict(job,input=dict(job['input'],checkpoint_turn=turn))
                        candidate = await asyncio.to_thread(self.repository.capture,checkpoint_job,attempt_id,path,report)
                        value = {'candidate':candidate,'turn':turn,'report':report}
                        await self.event(attempt_id,'debug_checkpoint',value)
                        await self.replay()
                        return value
                    result = await self.execution.run(job,path,attempt_id,log,
                        self.command_queues[attempt_id],command_result,checkpoint,lifecycle)
                    if (self.repository.git(path,'status','--porcelain') or
                            self.repository.git(path,'rev-parse','HEAD').decode().strip() != result['candidate']['head_sha']):
                        raise Problem('invalid_candidate','Workspace changed after passing checkpoint.')
                    value = {'report':result['report'],'candidate':result['candidate']}
                else:
                    result = await self.execution.run(job, path, attempt_id, log, self.command_queues[attempt_id], command_result, lifecycle=lifecycle)
                    candidate = await asyncio.to_thread(self.repository.capture, job, attempt_id, path, result)
                    value = {'report': result, 'candidate': candidate}
            elif step in ('verify', 'review'):
                path = await asyncio.to_thread(self.repository.snapshot, job['input']['candidate'],
                                               attempt_id, step == 'review')
                if step == 'review':
                    from cursus.artifact_control import file_refs
                    inputs = []
                    for ref in file_refs(job['input']):
                        inputs.append((ref, await self.transport.download(ref, attempt_id)))
                    await asyncio.to_thread(self.repository.evidence_files, path, inputs)
                configured = self.execution.verifier if step == 'verify' else self.execution.configured(job['invocation'])
                self.assign(path, configured, readonly=step == 'review')
                value = await self.execution.run(job, path, attempt_id, log)
                if step == 'verify':
                    from cursus.runner_files import evidence
                    value = evidence(self, attempt_id, value)
            elif step in ('plan', 'scout', 'interview', 'debate'):
                if step == 'scout':
                    data = job['input']
                    candidate = {'repo': data['repo'], 'head_sha': data['base_sha']}
                    path = await asyncio.to_thread(self.repository.snapshot, candidate, attempt_id, True)
                else:
                    path = self.repository.reviews / attempt_id
                    path.mkdir(mode=0o755)
                value = await self.execution.run(job, path, attempt_id, log)
            else:
                value = await asyncio.to_thread(self.repository.perform, job, attempt_id)
            final = {'kind': 'completed', 'value': value}
        except Problem as exc:
            final = {'kind': 'canceled' if exc.code == 'canceled' else 'unknown' if exc.code in ('publication_unknown', 'unknown_stop') else 'failed',
                     'classification': exc.code, 'reason': exc.message}
        except Exception:
            final = {'kind': 'failed', 'classification': 'execution_error', 'reason': 'Runner operation failed.'}
        self.active.pop(attempt_id, None)
        self.command_queues.pop(attempt_id, None)
        self.progress('finished', job, attempt_id, final['kind'])
        await self.event(attempt_id, 'final', final)
        await self.replay()
        return final

    async def apply_commands(self, commands):
        for command in sorted(commands, key=lambda c:c['action'] != 'stop'):
            if any(r['kind']=='command_intent' and r['value']['id']==command['id'] for r in self.journal.records):
                continue
            queue = self.command_queues.get(command['attempt_id'])
            if queue is None:
                granted = any(r['kind']=='grant' and r['value']['attempt_id']==command['attempt_id'] for r in self.journal.records)
                launched = any(r['kind']=='launch' and r['value']==command['attempt_id'] for r in self.journal.records)
                if command['action']=='stop' and granted and not launched:
                    self.pending_claims.pop(command['attempt_id'], None)
                    self.pending_status.pop(command['attempt_id'], None)
                    self.record('command_intent',command)
                    await self.event(command['attempt_id'],'command_result',{'command_id':command['id'],'disposition':'stopped'})
                    await self.event(command['attempt_id'],'final',{'kind':'canceled','reason':'Grant was canceled before launch.'})
                    await self.replay()
                continue
            self.record('command_intent',command)
            await queue.put(command)

    async def serve(self):
        heartbeat = asyncio.create_task(self.heartbeat())
        worker = asyncio.create_task(self.work_loop())
        flush = asyncio.create_task(self.flush())
        try:
            done, _ = await asyncio.wait((heartbeat, worker, flush), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
            raise Problem('supervision', 'Runner supervision stopped; intake closed.')
        finally:
            heartbeat.cancel()
            worker.cancel()
            flush.cancel()
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(heartbeat,worker,flush,*self.tasks, return_exceptions=True)

    def storage_pending(self):
        done = {r['value'] for r in self.journal.records if r['kind']=='workspace_cleaned'}
        return list(dict.fromkeys(r['value']['attempt'] for r in self.journal.records if r['kind']=='workspace_cleanup' and r['value']['attempt'] not in done))

    async def cleanup_storage(self):
        if not self.runtime:
            return
        for attempt in self.storage_pending()[:4]:
            if attempt in self.runtime.entries or attempt in self.active:
                continue
            validate('Id',attempt)
            try:
                for root in (self.repository.worktrees,self.repository.reviews):
                    target = root / attempt
                    if target.is_symlink():
                        target.unlink()
                    elif target.exists():
                        def remove():
                            # Read-only review snapshots deliberately deny writes.
                            # Reclaim only after the container is gone, and never
                            # follow repository symlinks while restoring directory access.
                            for _, _, _, fd in os.fwalk(target, follow_symlinks=False):
                                if os.fstat(fd).st_uid != os.getuid():
                                    raise PermissionError('Workspace directory ownership differs')
                                os.fchmod(fd,0o700)
                            shutil.rmtree(target)
                        await asyncio.to_thread(remove)
                    directory = os.open(root,os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                self.record('workspace_cleaned',attempt)
            except OSError:
                # The durable cleanup item stays pending and visible on heartbeat.
                pass

    async def flush(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.replay()
                if self.runtime and time.monotonic() >= getattr(self, 'next_storage_cleanup',0):
                    self.next_storage_cleanup = time.monotonic() + 10
                    await self.cleanup_storage()
            except (OSError, Problem):
                self.reconciled = False

    async def heartbeat(self):
        failures = 0
        while failures < 5:
            await asyncio.sleep(10)
            try:
                slots = dict.fromkeys(self.capacities, 0)
                for slot in self.active.values():
                    slots[slot] += 1
                directive = await self.exchange(f'runners/{self.id}/heartbeat', {'slots':slots,
                    'spool_bytes':self.journal.path.stat().st_size, 'boot_id':self.boot_id,
                    'health':('degraded' if self.runtime and (self.storage_pending() or any(e['state']=='uncertain' for e in self.runtime.entries.values())) else 'waiting' if self.pending_claims else 'executing' if self.active else 'ready'),
                    **({'execution': self.runtime.status() + list(self.pending_status.values()) + [dict(attempt=a,lane='storage',state='cleanup',since=next(r['value']['since'] for r in self.journal.records if r['kind']=='workspace_cleanup' and r['value']['attempt']==a),reason='Workspace deletion pending; retried automatically every 10s. Inspect filesystem permissions/free space.') for a in self.storage_pending()], 'capacity': self.capacities} if self.runtime else {})})
                await self.apply_commands(directive['commands'])
                failures = 0
            except (OSError, Problem) as exc:
                self.reconciled = False
                failures += 1
                if isinstance(exc, Problem) and exc.code == 'unauthorized':
                    self.intake_denied = True
                    return

    async def work_loop(self):
        self.activation = str(uuid4())
        failures, fault_started = 0, None
        tasks = self.tasks
        while True:
            try:
                if getattr(self, 'intake_denied', False):
                    raise Problem('unauthorized', 'Runner authorization denied.')
                if not self.reconciled:
                    await self.reconcile()
                    await self.replay()
                    directive = await self.reconcile()
                    await self.apply_commands(directive['commands'])
                    for held in directive['held_claims']:
                        launched = any(r['kind'] == 'launch' and r['value'] == held['attempt_id'] for r in self.journal.records)
                        finished = any(r['kind']=='event' and r['value']['attempt_id']==held['attempt_id'] and r['value']['kind']=='final' for r in self.journal.records)
                        if not launched and not finished:
                            if not any(r['kind'] == 'grant' and r['value']['attempt_id'] == held['attempt_id'] for r in self.journal.records):
                                self.record('grant', validate('Claim', held))
                            self.pending_claims[held['attempt_id']] = held
                if not self.reconciled:
                    raise Problem('recovery_required', 'Unreconciled claims require operator evidence.')
                for task in list(tasks):
                    if task.done():
                        tasks.remove(task)
                        try:
                            await task
                        except Exception as exc:
                            import logging
                            from datetime import datetime, timezone
                            logging.getLogger('cursus.runner').error(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),service='runner',event='session_task_failed',attempt_id=task.get_name(),classification=type(exc).__name__,reason='Reconciliation required; other sessions remain supervised.')))
                            self.reconciled = False
                if self.runtime and time.monotonic() >= self.next_cleanup:
                    self.next_cleanup = time.monotonic() + 10
                    outcomes = await self.runtime.recover()
                    if any(outcomes.values()):
                        self.recovered_stops.update(a for a, stopped in outcomes.items() if stopped)
                        self.reconciled = False
                if not self.reconciled:
                    continue
                for attempt, held in list(self.pending_claims.items()):
                    if attempt not in self.active:
                        self.active[attempt] = held['job']['slot']
                        del self.pending_claims[attempt]
                        tasks.add(asyncio.create_task(self.dispatch(held), name=held['attempt_id']))
                granted = False
                # Claims remain bounded centrally; local counts avoid polling
                # a full slot while existing tasks retain process ownership.
                lanes = list(self.capacities)
                self.poll_rotation = (self.poll_rotation + 1) % len(lanes)
                lanes = lanes[self.poll_rotation:] + lanes[:self.poll_rotation]
                for slot in lanes:
                    capacity = self.capacities[slot]
                    for _ in range(capacity - list(self.active.values()).count(slot) - sum(c['job']['slot'] == slot for c in self.pending_claims.values())):
                        claim = await self.claim(slot)
                        if claim:
                            granted = True
                            self.active[claim['attempt_id']] = slot
                            tasks.add(asyncio.create_task(self.dispatch(claim), name=claim['attempt_id']))
                failures, fault_started = 0, None
                if not granted:
                    await asyncio.sleep(1)
            except (OSError, Problem) as exc:
                self.reconciled = False
                if isinstance(exc, Problem) and exc.code in ('unauthorized', 'recovery_required', 'storage', 'journal_corrupt'):
                    raise
                failures += 1
                fault_started = fault_started or time.monotonic()
                if failures >= 5 or time.monotonic() - fault_started >= 120:
                    raise Problem('transport', 'Runner transport retry budget exhausted.') from None
                await asyncio.sleep(min(30, 2 ** failures) + random.uniform(0, 1))
