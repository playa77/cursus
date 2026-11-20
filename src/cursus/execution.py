"""Direct native CLI/verifier protocols inside session containers (ADR 0009).

The explicit allow_test_identity seam is only for controlled executable fixtures.
"""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import re
import signal
from cursus.contracts import Problem, canonical_json, decode_json, _object


MAX_OUTPUT = 1024 * 1024


def sanitize(text):
    return re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|password)\s*[=:]\s*)[^\s"\']+',
                  r'\1[REDACTED]', text)


def report(value):
    _object(value, {'summary', 'suggested_files'})
    if not isinstance(value['summary'], str) or not value['summary'].strip():
        raise Problem('missing_report', 'Missing completion summary.')
    if not isinstance(value['suggested_files'], list) or not all(isinstance(p, str) for p in value['suggested_files']):
        raise Problem('missing_report', 'Invalid suggested file list.')
    return value


def review(value, criteria):
    _object(value, {'verdict', 'criteria', 'findings', 'required_repairs'})
    if value['verdict'] not in ('accept', 'repair', 'reject'):
        raise Problem('invalid_review', 'Invalid review disposition.')
    if not isinstance(value['criteria'], list) or len(value['criteria']) != len(criteria):
        raise Problem('invalid_review', 'Review does not cover every criterion.')
    for expected, item in zip(criteria, value['criteria']):
        _object(item, {'id', 'passed', 'evidence'})
        if item['id'] != expected['id'] or type(item['passed']) is not bool or not isinstance(item['evidence'], list) or not item['evidence']:
            raise Problem('invalid_review', 'Criterion review lacks observed evidence.')
    if not isinstance(value['findings'], list) or not isinstance(value['required_repairs'], list):
        raise Problem('invalid_review', 'Invalid review findings.')
    if value['verdict'] == 'accept' and (not all(item['passed'] for item in value['criteria']) or value['required_repairs']):
        raise Problem('invalid_review', 'Acceptance contradicts criterion outcomes.')
    return value


class Execution:
    def __init__(self, profiles, identities, verifier, allow_test_identity=False, runtime=None):
        self.profiles, self.identities, self.verifier = profiles, identities, verifier
        self.runtime = runtime
        if not allow_test_identity and runtime is None:
            raise Problem("identity_boundary", "Production requires the container runtime.")
        self.allow_test_identity = allow_test_identity

    def identity(self, configured):
        if self.runtime:
            from types import SimpleNamespace
            return SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name='session')
        user = pwd.getpwnam(configured['user'])
        if user.pw_uid == 0 or (os.geteuid() != 0 and not self.allow_test_identity):
            raise Problem('identity_boundary', 'Execution requires distinct unprivileged identities.')
        return user

    def configured(self, invocation):
        if self.runtime:
            return {'home': '/home/session', 'user': 'session'}
        return self.identities[invocation['role']['cli']]

    def authorize(self, invocation):
        role = invocation['role']
        cli = role['cli']
        profile = self.profiles[cli]
        profile = dict(profile, **profile.get('role_profiles', {}).get(role['name'], {}))
        if role['name'] not in profile['qualified_roles'] or role['model'] != profile['model']:
            raise Problem('profile_mismatch', 'Role/model is not qualified.')
        if (role['tier'] == 'production' and cli != 'pi') or role['tier'] not in ('production', 'organization'):
            raise Problem('profile_mismatch', 'Invalid production CLI.')
        if role['tier'] == 'organization' and set(role['tools']) - {'read', 'list', 'search'}:
            raise Problem('profile_mismatch', 'Reviewer/organization tools must be read-only.')
        if set(role['tools']) != set(profile['tool_allowlist']) or '*' in role['tools']:
            raise Problem('profile_mismatch', 'Role tools exceed qualified authority.')
        if invocation['profile_digest'] != self.profiles['digest']:
            raise Problem('profile_mismatch', 'Invocation profile digest differs.')
        for key in ('provider', 'reasoning'):
            if role.get(key) != profile.get(key):
                raise Problem('profile_mismatch', 'Invocation tuple is not qualified.')
        binary = Path(profile['binary'])
        if not binary.is_absolute() or (not self.runtime and sha256(binary.read_bytes()).hexdigest() != profile['binary_digest']):
            raise Problem('profile_mismatch', 'CLI binary digest changed.')
        if not profile.get('probe_evidence') or not profile.get('clean_config_argv'):
            raise Problem('profile_mismatch', 'Missing installed-version capability evidence.')
        if not self.allow_test_identity:
            tokens = profile['fixed_argv']
            required = {'pi': ['--mode', 'rpc' if profile['prompt_transport'] == 'rpc' else 'json'],
                        'claude': ['-p', '--output-format', 'stream-json'],
                        'codex': ['exec', '--json'], 'agy': ['-p', '--output-format', 'stream-json']}[cli]
            if any(token not in tokens for token in required):
                raise Problem('profile_mismatch', 'Required direct CLI invocation family is missing.')
        argv = [str(binary), *profile['fixed_argv']]
        if set(role['tools']) <= {'read', 'list', 'search'}:
            if not profile.get('read_only_argv'):
                raise Problem('profile_mismatch', 'Missing read-only qualification.')
            argv += profile['read_only_argv']
        argv += profile['clean_config_argv']
        configured = self.configured(invocation)
        if not self.allow_test_identity and not self.runtime and (profile.get('user') != configured['user'] or profile.get('home') != configured['home']):
            raise Problem('profile_mismatch', 'Qualified privilege identity differs.')
        return profile, argv, self.identity(configured)

    async def child(self, argv, workspace, user, home, stdin, timeout, sink=None, rpc=False, commands=None, command_sink=None, checkpoint=None, lifecycle=None):
        environment = {'HOME': home, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
                       'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': home}
        privileges = {'user': user.pw_uid, 'group': user.pw_gid, 'extra_groups': []} if os.geteuid() == 0 else {}
        pipes = dict(stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                     stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=65537)
        if self.runtime:
            process = await self.runtime.spawn(argv, Path(workspace), **pipes)
        else:
            process = await asyncio.create_subprocess_exec(*argv, cwd=workspace, env=environment,
                                                          **pipes, **privileges)
        output, diagnostics = bytearray(), bytearray()
        request_id = 'cursus-turn-1'
        pending_commands = {}
        stopped = False
        stop_commands = []
        debug_decisions = asyncio.Queue()
        turn_start = 0
        turn = 0
        selected = None
        debug_result = None
        async def consume_commands():
            nonlocal stopped
            while commands is not None:
                item = await commands.get()
                if item['action'] == 'stop':
                    stopped = True
                    stop_commands.append(item)
                    await debug_decisions.put(item)
                    if process.returncode is None:
                        os.killpg(process.pid,signal.SIGTERM)
                    return
                if checkpoint and item['action'] in ('continue_debug','finish_debug'):
                    await debug_decisions.put(item)
                    continue
                if not rpc:
                    if command_sink:
                        await command_sink({'command_id':item['id'],'disposition':'rejected','reason':'Execution has no RPC command channel.'})
                    continue
                pending_commands[item['id']] = item
                process.stdin.write(canonical_json({'id':item['id'],'type':'steer','message':item['text']}) + b'\n')
                await process.stdin.drain()
        command_task = asyncio.create_task(consume_commands())
        async def read_output():
            nonlocal request_id,turn_start,turn,selected,debug_result
            terminal = False
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                output.extend(line)
                if len(output) > MAX_OUTPUT:
                    raise Problem('output_limit', 'Structured output exceeds its bound.')
                if rpc:
                    frame = decode_json(line)
                    if frame.get('type') == 'response':
                        if frame.get('id') in pending_commands:
                            item = pending_commands.pop(frame['id'])
                            if command_sink:
                                await command_sink({'command_id':item['id'], 'disposition':'accepted' if frame.get('success') else 'rejected'})
                        elif frame.get('id') != request_id or not frame.get('success'):
                            raise Problem('protocol', 'RPC response correlation or acceptance failed.')
                    if frame.get('type') == 'agent_end':
                        terminal = True
                        if checkpoint:
                            turn += 1
                            report_value = self.normalize('pi', bytes(output[turn_start:]))
                            report(report_value)
                            selected = await checkpoint(turn,report_value)
                            while True:
                                item = await debug_decisions.get()
                                if item['action'] == 'stop':
                                    break
                                if item.get('checkpoint') != selected:
                                    if command_sink:
                                        await command_sink({'command_id':item['id'],'disposition':'rejected','reason':'Checkpoint differs from idle turn.'})
                                    continue
                                if item['action'] == 'finish_debug':
                                    if not item.get('evidence') or not all(e['passed'] for e in item['evidence']):
                                        raise Problem('invalid_evidence','Finish needs passing checkpoint verification.')
                                    debug_result = selected
                                    process.stdin.close()
                                    if command_sink:
                                        await command_sink({'command_id':item['id'],'disposition':'accepted'})
                                else:
                                    request_id = item['id']
                                    pending_commands[request_id] = item
                                    turn_start = len(output)
                                    process.stdin.write(canonical_json({'id':request_id,'type':'prompt',
                                        'message':'Continue debugging using this verifier evidence: ' + canonical_json(item['evidence']).decode()}) + b'\n')
                                    await process.stdin.drain()
                                break
                        else:
                            process.stdin.close()
                if sink:
                    await sink({'stream': 'stdout', 'text': sanitize(line.decode('utf-8'))})
            return terminal
        async def read_error():
            while chunk := await process.stderr.read(4096):
                diagnostics.extend(chunk)
                if len(diagnostics) > MAX_OUTPUT:
                    raise Problem('output_limit', 'Diagnostic output exceeds its bound.')
        try:
            async with asyncio.timeout(timeout):
                if lifecycle:
                    await lifecycle(process.pid)
                process.stdin.write(stdin)
                await process.stdin.drain()
                if not rpc:
                    process.stdin.close()
                terminal, _ = await asyncio.gather(read_output(), read_error())
                code = await process.wait()
                if stopped:
                    raise Problem('canceled', 'Execution stopped by operator command.')
                if rpc and not terminal:
                    raise Problem('missing_terminal', 'RPC did not finish a qualifying turn.')
                if checkpoint and debug_result is None:
                    raise Problem('missing_terminal','Debug process exited without an approved finish.')
                return code, canonical_json(debug_result) if checkpoint else bytes(output), sanitize(diagnostics.decode('utf-8', errors='replace'))
        except (TimeoutError, ValueError, TypeError, KeyError, AttributeError, Problem) as exc:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
            if isinstance(exc, Problem):
                raise
            raise Problem('execution_timeout', 'Execution failed its framing/time bound.') from None
        finally:
            command_task.cancel()
            await asyncio.gather(command_task,return_exceptions=True)
            # A CLI may exit while descendants hold execution authority. The
            # owned process group is terminated before candidate capture.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.returncode is None:
                await process.wait()
            # A remaining group may include descendants even after the leader
            # exited. Without proof of cleanup, withhold candidate capture.
            for _ in range(20):
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(.05)
            else:
                raise Problem('unknown_stop', 'Execution group termination is not confirmed.')
            if stopped and command_sink:
                # Stop is resolved only after the owned group has disappeared.
                for command in stop_commands:
                    await command_sink({'command_id':command['id'],'disposition':'stopped'})
            for command in pending_commands.values():
                if command_sink:
                    await command_sink({'command_id':command['id'],'disposition':'uncertain'})

    def normalize(self, cli, raw):
        frames = [decode_json(line) for line in raw.splitlines() if line.strip()]
        answer, terminal = None, False
        for frame in frames:
            kind = frame.get('type')
            if kind in ('error', 'turn.failed') or frame.get('is_error') is True:
                raise Problem('cli_failed', 'CLI reported failure.')
            if cli == 'pi':
                if kind == 'message_end' and frame.get('message', {}).get('role') == 'assistant':
                    answer = ''.join(part['text'] for part in frame['message']['content'] if part.get('type') == 'text')
                if kind == 'agent_end':
                    terminal = True
            elif cli == 'codex':
                if kind == 'item.completed' and frame.get('item', {}).get('type') == 'agent_message':
                    answer = frame['item']['text']
                if kind == 'turn.completed':
                    terminal = True
            elif cli == 'agy' and frame.get('event') == 'result':
                result = frame.get('result', {})
                if result.get('status') != 'SUCCESS':
                    raise Problem('cli_failed', 'Antigravity reported non-success terminal state.')
                answer, terminal = result.get('response'), True
            elif cli in ('claude', 'agy'):
                if kind == 'result' and frame.get('subtype') == 'success':
                    answer, terminal = frame.get('result'), True
        if not terminal or not isinstance(answer, str):
            raise Problem('missing_terminal', 'No qualified terminal assistant response.')
        return decode_json(sanitize(answer))

    async def run(self, job, workspace, attempt_id, sink=None, commands=None, command_sink=None, checkpoint=None, lifecycle=None):
        if not self.runtime:
            return await self._run(job, workspace, attempt_id, sink, commands, command_sink, checkpoint, lifecycle)
        item = self.runtime.entries[attempt_id]
        item['workspace'] = str(workspace)
        self.runtime.save()
        token = self.runtime.current.set(attempt_id)
        try:
            readonly = job.get('invocation', {}).get('role', {}).get('tools', [])
            readonly = job['step'] != 'verify' and not (set(readonly) - {'read', 'list', 'search'})
            await self.runtime.prepare(attempt_id, workspace, readonly)
            return await self._run(job, workspace, attempt_id, sink, commands, command_sink, checkpoint, lifecycle)
        finally:
            self.runtime.current.reset(token)
            clean = await asyncio.shield(self.runtime.cleanup(attempt_id))
            self.runtime.owned.discard(attempt_id)
            if not clean:
                raise Problem('unknown_stop', 'Container cleanup pending; execution capacity remains unavailable.')

    async def _run(self, job, workspace, attempt_id, sink=None, commands=None, command_sink=None, checkpoint=None, lifecycle=None):
        if job['step'] == 'verify':
            return await self.verify(job, workspace, attempt_id)
        invocation = job['invocation']
        profile, argv, user = self.authorize(invocation)
        transport = profile['prompt_transport']
        prompt = invocation['prompt_text']
        if transport == 'stdin':
            stdin = prompt.encode()
        elif transport == 'argument':
            argv.append(prompt)
            stdin = b''
        elif transport == 'rpc':
            stdin = canonical_json({'id': 'cursus-turn-1', 'type': 'prompt', 'message': prompt}) + b'\n'
        else:
            raise Problem('profile_mismatch', 'Unqualified prompt transport.')
        code, raw, diagnostic = await self.child(argv, workspace, user,
            self.configured(invocation)['home'], stdin, invocation['role']['timeout_seconds'], sink,
            rpc=transport == 'rpc', commands=commands, command_sink=command_sink, checkpoint=checkpoint, lifecycle=lifecycle)
        if code:
            raise Problem('cli_failed', 'CLI process failed.')
        result = decode_json(raw) if checkpoint else self.normalize(invocation['role']['cli'], raw)
        if job['step'] == 'produce':
            report(result)
        if job['step'] == 'review':
            review(result, job['input']['criteria'])
        return result

    async def verify(self, job, workspace, attempt_id):
        candidate = job['input']['candidate']
        checks = {item['id']: item for item in job['input']['checks']}
        user = self.identity(self.verifier)
        evidence = []
        for criterion in job['input']['criteria']:
            check = criterion['check']
            if check['kind'] == 'review':
                continue
            if check['kind'] != 'command' or check['command_id'] not in checks:
                raise Problem('invalid_check', 'Check is not an enrolled command.')
            command = checks[check['command_id']]
            path = (Path(workspace) / command['cwd']).resolve()
            if not path.is_relative_to(Path(workspace).resolve()):
                raise Problem('invalid_check', 'Check cwd escapes snapshot.')
            code, raw, diagnostic = await self.child(command['argv'], path, user, self.verifier['home'],
                                                      b'', command['timeout_seconds'])
            text = sanitize(raw.decode('utf-8', errors='replace') + diagnostic)
            passed = code == check['expected_exit'] and check.get('required_literal', '') in text
            evidence.append({'criterion_id': criterion['id'], 'candidate': candidate,
                             'passed': passed, 'observed_exit': code, 'output': text[:65536],
                             'verifier_attempt_id': attempt_id})
        return evidence
