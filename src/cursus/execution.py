"""Direct, pinned CLI and verifier execution under isolated child identities."""

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
    def __init__(self, profiles, identities, verifier, allow_test_identity=False):
        self.profiles, self.identities, self.verifier = profiles, identities, verifier
        self.allow_test_identity = allow_test_identity

    def identity(self, configured):
        user = pwd.getpwnam(configured['user'])
        if user.pw_uid == 0 or (os.geteuid() != 0 and not self.allow_test_identity):
            raise Problem('identity_boundary', 'Execution requires distinct unprivileged identities.')
        return user

    def authorize(self, invocation):
        role = invocation['role']
        cli = role['cli']
        profile = self.profiles[cli]
        if role['name'] not in profile['qualified_roles'] or role['model'] != profile['model']:
            raise Problem('profile_mismatch', 'Role/model is not qualified.')
        if (role['tier'] == 'production' and cli != 'pi') or role['tier'] not in ('production', 'organization'):
            raise Problem('profile_mismatch', 'Invalid production CLI.')
        if role['tier'] == 'organization' and set(role['tools']) - {'read', 'list', 'search'}:
            raise Problem('profile_mismatch', 'Reviewer/organization tools must be read-only.')
        if set(role['tools']) - set(profile['tool_allowlist']) or '*' in role['tools']:
            raise Problem('profile_mismatch', 'Role tools exceed qualified authority.')
        if invocation['profile_digest'] != self.profiles['digest']:
            raise Problem('profile_mismatch', 'Invocation profile digest differs.')
        for key in ('provider', 'reasoning'):
            if role.get(key) != profile.get(key):
                raise Problem('profile_mismatch', 'Invocation tuple is not qualified.')
        binary = Path(profile['binary'])
        if not binary.is_absolute() or sha256(binary.read_bytes()).hexdigest() != profile['binary_digest']:
            raise Problem('profile_mismatch', 'CLI binary digest changed.')
        if not profile.get('probe_evidence') or not profile.get('clean_config_argv'):
            raise Problem('profile_mismatch', 'Missing installed-version capability evidence.')
        argv = [str(binary), *profile['fixed_argv']]
        if role['tier'] == 'organization':
            if not profile.get('read_only_argv'):
                raise Problem('profile_mismatch', 'Missing read-only qualification.')
            argv += profile['read_only_argv']
        argv += profile['clean_config_argv']
        return profile, argv, self.identity(self.identities[cli])

    async def child(self, argv, workspace, user, home, stdin, timeout, sink=None, rpc=False):
        environment = {'HOME': home, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
                       'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': str(workspace)}
        privileges = {'user': user.pw_uid, 'group': user.pw_gid, 'extra_groups': []} if os.geteuid() == 0 else {}
        process = await asyncio.create_subprocess_exec(*argv, cwd=workspace, env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=65537, **privileges)
        output, diagnostics = bytearray(), bytearray()
        request_id = 'cursus-turn-1'
        async def read_output():
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
                    if frame.get('type') == 'response' and (frame.get('id') != request_id or not frame.get('success')):
                        raise Problem('protocol', 'RPC response correlation or acceptance failed.')
                    if frame.get('type') == 'agent_end':
                        terminal = True
                        process.stdin.close()
                if sink:
                    await sink({'stream': 'stdout', 'text': sanitize(line.decode('utf-8'))})
            return terminal
        async def read_error():
            while chunk := await process.stderr.read(4096):
                diagnostics.extend(chunk)
                if len(diagnostics) > MAX_OUTPUT:
                    raise Problem('output_limit', 'Diagnostic output exceeds its bound.')
        process.stdin.write(stdin)
        await process.stdin.drain()
        if not rpc:
            process.stdin.close()
        try:
            async with asyncio.timeout(timeout):
                terminal, _ = await asyncio.gather(read_output(), read_error())
                code = await process.wait()
                if rpc and not terminal:
                    raise Problem('missing_terminal', 'RPC did not finish a qualifying turn.')
                return code, bytes(output), sanitize(diagnostics.decode('utf-8', errors='replace'))
        except (TimeoutError, ValueError, Problem) as exc:
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
            # A CLI may exit while descendants hold execution authority. The
            # owned process group is terminated before candidate capture.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

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
            elif cli in ('claude', 'agy'):
                if kind == 'result' and frame.get('subtype') == 'success':
                    answer, terminal = frame.get('result'), True
        if not terminal or not isinstance(answer, str):
            raise Problem('missing_terminal', 'No qualified terminal assistant response.')
        return decode_json(answer)

    async def run(self, job, workspace, attempt_id, sink=None):
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
            self.identities[invocation['role']['cli']]['home'], stdin, invocation['role']['timeout_seconds'], sink,
            rpc=transport == 'rpc')
        if code:
            raise Problem('cli_failed', 'CLI process failed.')
        result = self.normalize(invocation['role']['cli'], raw)
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
