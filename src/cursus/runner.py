"""Durable runner journal and bounded, runner-initiated HTTPS exchange."""

import asyncio
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
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, decode_json, validate


from cursus.journal import Journal
from cursus.capacity import lane, fixture_capacity


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
    def __init__(self, runner_id, journal, transport, repository=None, execution=None, capacity=None):
        self.id, self.journal, self.transport = runner_id, journal, transport
        self.repository, self.execution = repository, execution
        self.capacity = capacity or fixture_capacity()
        self.reconciled = False
        self.activation = str(uuid4())
        self.active = {}
        self.command_queues = {}
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.replay_lock = asyncio.Lock()
        self.tasks = set()
        from cursus.identities import IdentityPool
        self.pool = IdentityPool(execution.pool,journal) if execution and execution.pool else None
        if self.pool and execution.resources:
            for record in journal.records:
                if record['kind']=='grant' and record['value']['attempt_id'] in self.pool.held:
                    claim = record['value']
                    execution.resources.held[claim['attempt_id']] = execution.resources.amount(claim['job'])

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
            finals = [r['value']['payload'] for r in self.journal.records if r['kind']=='event'
                      and r['value']['attempt_id']==attempt_id and r['value']['kind']=='final']
            final = bool(finals and finals[-1]['kind']!='unknown')
            starts = [r['value'] for r in self.journal.records if r['kind']=='process_context' and r['value']['attempt_id']==attempt_id]
            stopped = starts and starts[-1]['boot_id'] != self.boot_id
            observations.append({'attempt_id': attempt_id,
                                 'kind': 'terminal_pending' if final else 'live' if attempt_id in self.active else 'stopped' if stopped else 'unknown' if launched else 'never_started',
                                 'reason': 'Durable journal observation.'})
        directive = await self.exchange(f'runners/{self.id}/reconcile', {
            'generation': self.journal.generation, 'observations': observations, 'pending_request_ids': pending, 'capacity': self.capacity})
        for attempt_id,disposition in directive['dispositions'].items():
            if disposition=='stop-stale' and attempt_id in self.command_queues:
                prior=any(r['kind']=='stale_stop' and r['value']==attempt_id for r in self.journal.records)
                if not prior:
                    self.record('stale_stop',attempt_id)
                    await self.command_queues[attempt_id].put({'id':str(uuid4()),'attempt_id':attempt_id,'action':'stop'})
        held_ids = {c['attempt_id'] for c in directive['held_claims']}
        resolved = {r['value']['payload']['command_id'] for r in self.journal.records
                    if r['kind']=='event' and r['value']['kind']=='command_result'}
        for record in self.journal.records:
            if record['kind']=='command_intent':
                command = record['value']
                if command['id'] not in resolved and command['attempt_id'] in held_ids and command['attempt_id'] not in self.active:
                    await self.event(command['attempt_id'],'command_result',
                        {'command_id':command['id'],'disposition':'uncertain','reason':'Prior RPC delivery has no durable result.'})
                    resolved.add(command['id'])
        if self.pool:
            for observation in observations:
                if observation['attempt_id'] not in self.pool.held:
                    continue
                if observation['kind']=='stopped' and directive['dispositions'].get(observation['attempt_id'])=='ignore-stale':
                    self.release_identity(observation['attempt_id'])
                elif observation['kind']=='terminal_pending' and observation['attempt_id'] not in self.active:
                    self.release_identity(observation['attempt_id'])
        self.record('directive', directive)
        self.reconciled = directive['reconciled']
        return directive

    async def claim(self, slot, request_id=None, provider=None, wait=True):
        if not self.reconciled:
            raise Problem('state_conflict', 'Runner must reconcile first.')
        request_id = request_id or str(uuid4())
        self.record('pending', {'id': request_id, 'slot': slot})
        result = await self.exchange('jobs/next', dict(slot=slot, **({'provider':provider} if provider else {}), **({} if wait else {'wait':'0'})), request_id, 'GET')
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
        attempts = {r['value']['attempt_id'] for r in self.journal.records if r['kind']=='grant'}
        for attempt_id in attempts:
            batch = []
            for record in self.journal.records:
                if record['kind'] != 'event':
                    continue
                event = record['value']
                if event['attempt_id'] != attempt_id or event['seq'] <= positions.get(attempt_id,0):
                    continue
                batch.append(event)
                if len(batch)==100:
                    ack = await self.exchange(f'attempts/{attempt_id}/events',batch)
                    self.record('ack',dict(ack,attempt_id=attempt_id))
                    batch = []
            if batch:
                ack = await self.exchange(f'attempts/{attempt_id}/events',batch)
                self.record('ack',dict(ack,attempt_id=attempt_id))

    def assign(self, path, configured, readonly=False):
        if not configured or os.geteuid() != 0:
            return
        user = pwd.getpwnam(configured['user'])
        # Never traverse symlinks while preparing the privilege boundary.
        if not readonly:
            for entry in [path, *path.rglob('*')]:
                if entry.name == '.git' or entry.is_symlink():
                    continue
                os.chown(entry, user.pw_uid, user.pw_gid, follow_symlinks=False)
        if readonly:
            os.chown(path,0,user.pw_gid)
        path.chmod(0o550 if readonly else 0o700)

    def progress(self, event, job, attempt_id, outcome=None):
        import logging
        from datetime import datetime, timezone
        from cursus import __version__
        logging.getLogger('cursus.runner').info(json.dumps({
            'time': datetime.now(timezone.utc).isoformat(), 'service': 'runner',
            'version': __version__, 'event': event, 'job_id': job['id'],
            'attempt_id': attempt_id, 'step': job['step'], 'outcome': outcome}))

    def release_identity(self, attempt_id):
        """Remove old UID authority before lending that UID to another attempt."""
        from cursus.identities import remove_home
        if self.repository and os.geteuid()==0:
            for root in (self.repository.worktrees,self.repository.reviews):
                path = root / attempt_id
                if path.is_dir() and not path.is_symlink():
                    os.chown(path,0,0,follow_symlinks=False)
                    path.chmod(0o700)
        remove_home(self.execution.home_root,attempt_id)
        self.pool.release(attempt_id)
        if self.execution.resources:
            self.execution.resources.release(attempt_id)

    async def dispatch(self, claim):
        token = None
        attempt_id, job = claim['attempt_id'], claim['job']
        if any(r['kind']=='launch' and r['value']==attempt_id for r in self.journal.records):
            raise Problem('state_conflict','Launch intent exists; automatic relaunch forbidden.')
        if self.pool and job['slot'] != 'repository':
            from cursus.identities import prepare_home
            account = self.pool.acquire(attempt_id)
            if job['step']=='verify':
                source, auth = self.execution.verifier, []
            else:
                source = self.execution.native(job['invocation'])
                auth = source.get('auth_files',[])
            from cursus.identities import remove_home
            # A retained lease without launch intent proves this home was never
            # exposed to an execution. Rebuild a possibly partial preparation.
            remove_home(self.execution.home_root,attempt_id)
            try:
                configured = prepare_home(self.execution.home_root,attempt_id,account,source,auth)
            except BaseException:
                remove_home(self.execution.home_root,attempt_id)
                self.pool.release(attempt_id)
                if self.execution.resources:
                    self.execution.resources.release(attempt_id)
                raise
            configured['category'] = 'worker' if job['slot']=='worker' else 'verifier' if job['step']=='verify' else 'frontier'
            token = self.execution.pool_context.set(configured)
        try:
            return await self._dispatch(claim)
        finally:
            if token is not None:
                self.execution.pool_context.reset(token)
                finals = [r['value']['payload'] for r in self.journal.records if r['kind']=='event'
                          and r['value']['attempt_id']==attempt_id and r['value']['kind']=='final']
                if finals and finals[-1]['kind'] != 'unknown':
                    self.release_identity(attempt_id)
                # Unknown processes keep their identity; never reuse it by timeout.
            if self.execution and self.execution.resources:
                if not self.pool or attempt_id not in self.pool.held:
                    self.execution.resources.release(attempt_id)

    async def _dispatch(self, claim):
        job, attempt_id = claim['job'], claim['attempt_id']
        if any(r['kind'] == 'launch' and r['value'] == attempt_id for r in self.journal.records):
            raise Problem('state_conflict', 'Launch intent exists; automatic relaunch forbidden.')
        self.record('process_context', {'attempt_id':attempt_id,'boot_id':self.boot_id,'activation':self.activation})
        self.record('launch', attempt_id)
        self.active[attempt_id] = lane(job)
        self.command_queues[attempt_id] = asyncio.Queue()
        self.progress('started', job, attempt_id)
        await self.event(attempt_id, 'started', {'service_activation': self.activation,
                                              'time': __import__('datetime').datetime.now(
                                                  __import__('datetime').timezone.utc).isoformat()})
        async def log(payload):
            # Agent text is sanitized by Execution before reaching persistence.
            await self.event(attempt_id, 'log', payload)
        async def lifecycle(pid):
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
                configured = (self.execution.pool_context.get() or self.execution.verifier) if step == 'verify' else self.execution.configured(job['invocation'])
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
                self.assign(path,self.execution.configured(job['invocation']),readonly=True)
                value = await self.execution.run(job, path, attempt_id, log)
            else:
                value = await asyncio.to_thread(self.repository.perform, job, attempt_id)
            final = {'kind': 'completed', 'value': value}
        except Problem as exc:
            final = {'kind': 'canceled' if exc.code == 'canceled' else 'unknown' if exc.code in ('publication_unknown', 'unknown_stop') else 'failed',
                     'classification': exc.code, 'reason': exc.message}
        except (OSError, ValueError):
            final = {'kind': 'failed', 'classification': 'execution_error', 'reason': 'Runner operation failed.'}
        self.active.pop(attempt_id, None)
        self.command_queues.pop(attempt_id, None)
        self.progress('finished', job, attempt_id, final['kind'])
        await self.event(attempt_id, 'final', final)
        await self.replay()
        self.record('retire', claim['request_id'])
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
                    self.record('command_intent',command)
                    await self.event(command['attempt_id'],'command_result',{'command_id':command['id'],'disposition':'stopped'})
                    await self.event(command['attempt_id'],'final',{'kind':'canceled','reason':'Grant was canceled before launch.'})
                    await self.replay()
                continue
            self.record('command_intent',command)
            await queue.put(command)

    async def serve(self):
        heartbeat = asyncio.create_task(self.heartbeat())
        event_pump = asyncio.create_task(self.event_pump())
        try:
            await self.work_loop()
        finally:
            heartbeat.cancel()
            event_pump.cancel()
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(heartbeat,event_pump,*self.tasks, return_exceptions=True)

    async def event_pump(self):
        while True:
            await asyncio.sleep(1)
            if not self.reconciled:
                continue
            try:
                await self.replay()
            except (OSError,Problem):
                # The work loop owns bounded recovery; children continue to spool.
                self.reconciled = False

    async def heartbeat(self):
        failures = 0
        while failures < 5:
            await asyncio.sleep(10)
            try:
                slots = dict.fromkeys(self.capacity, 0)
                for slot in self.active.values():
                    slots[slot] += 1
                directive = await self.exchange(f'runners/{self.id}/heartbeat', {'slots':slots,
                    'spool_bytes':self.journal.path.stat().st_size, 'boot_id':self.boot_id,
                    'health':'executing' if self.active else 'ready'})
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
                            if self.execution and self.execution.resources:
                                if not self.execution.resources.available(held['job']):
                                    continue
                                self.execution.resources.reserve(held['attempt_id'],held['job'])
                            self.active[held['attempt_id']] = lane(held['job'])
                            tasks.add(asyncio.create_task(self.dispatch(held)))
                if not self.reconciled:
                    raise Problem('recovery_required', 'Unreconciled claims require operator evidence.')
                for task in list(tasks):
                    if task.done():
                        tasks.remove(task)
                        await task
                granted = False
                # Claims remain bounded centrally; local counts avoid polling
                # a full slot while existing tasks retain process ownership.
                for execution_lane, capacity in self.capacity.items():
                    slot = 'frontier' if execution_lane in ('claude','codex','agy','pi') else execution_lane
                    for _ in range(capacity - list(self.active.values()).count(execution_lane)):
                        if self.pool and slot!='repository' and len(self.pool.held)>=len(self.pool.accounts):
                            break
                        if self.execution and self.execution.resources and not self.execution.resources.available({'slot':slot}):
                            break
                        claim = await self.claim(slot, provider=execution_lane if slot=='frontier' else None, wait=False)
                        if claim:
                            if self.execution and self.execution.resources:
                                self.execution.resources.reserve(claim['attempt_id'],claim['job'])
                            granted = True
                            self.active[claim['attempt_id']] = lane(claim['job'])
                            tasks.add(asyncio.create_task(self.dispatch(claim)))
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
