"""Sole infrastructure composition root and offline-discoverable entry points."""

import argparse
import asyncio
import json
import sys
from uuid import uuid4
from cursus import __version__
from cursus.contracts import Problem, decode_json, validate


def parser():
    root = argparse.ArgumentParser(prog='cursus', description='Private evidence-driven work coordination.')
    root.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = root.add_subparsers(dest='command')
    for name in ('control', 'runner'):
        command = commands.add_parser(name)
        command.add_argument('--config', required=True)
    for name in ('submit', 'action', 'status'):
        command = commands.add_parser(name)
        command.add_argument('--socket', default='/run/cursus/operator.sock')
        if name == 'status':
            selection = command.add_mutually_exclusive_group()
            selection.add_argument('--phase-id')
            selection.add_argument('--attempt-id')
            selection.add_argument('--deployment', action='store_true')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--idempotency-key')
    return root


async def service(args):
    import logging
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    from cursus.config import load
    settings = load(args.command, args.config)
    if args.command == 'control':
        import asyncpg
        from cursus.control import Control
        from cursus.store import Store
        from cursus.http import serve
        pool = await asyncpg.create_pool(settings['dsn'], min_size=1, max_size=10)
        try:
            store = Store(pool)
            await store.migrate()
            from cursus.artifacts import Artifacts
            artifacts = Artifacts(settings['service']['artifact_root'])
            control = Control(settings, store, artifacts=artifacts)
            if hasattr(control, 'maintain'):
                await control.maintain('boot')
            async def maintenance():
                while True:
                    await asyncio.sleep(settings['limits']['heartbeat_seconds'])
                    await control.maintain('tick')
            timer = asyncio.create_task(maintenance())
            from cursus.browser import environment
            server = asyncio.create_task(serve(settings, control, environment()))
            try:
                done, _ = await asyncio.wait((timer,server), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
            finally:
                timer.cancel()
                server.cancel()
                await asyncio.gather(timer,server,return_exceptions=True)
        finally:
            await pool.close()
    else:
        import os
        from cursus.runner import HTTPS, Journal, Runner
        from cursus.repository import Repository, GitHub
        from cursus.execution import Execution
        if os.geteuid() == 0:
            raise Problem('identity_boundary', 'The runner must run as the non-root user whose CLI logins it uses.')
        service = settings['service']
        import pwd
        account = pwd.getpwnam(service['user'])
        if (account.pw_uid,account.pw_gid) != (os.getuid(),os.getgid()):
            raise Problem('identity_boundary', 'Runner service numeric identity differs from configuration.')
        journal = Journal(service['state_root'], settings['limits']['spool_bytes'])
        try:
            transport = HTTPS(service['origin'], settings['bearer'], journal.generation)
            enrollment = {(r['owner'], r['name']): r for r in settings['repositories']}
            publisher = settings['publisher']
            repository = Repository(service['repository_root'], service['worktree_root'], service['review_root'],
                enrollment, GitHub(publisher['github_credential_file']), publisher['git_binary'],
                publisher['git_credential_file'])
            from cursus.host import HostRuntime
            runtime = HostRuntime(settings['execution'], journal.root / 'execution', settings['capacity'])
            await runtime.preflight()
            execution = Execution(settings['profiles'], runtime)
            runner = Runner(service['runner_id'], journal, transport, repository, execution)
            await runner.serve()
        finally:
            journal.close()


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    if not args.command:
        root.print_help()
        return 0
    try:
        if args.command in ('control', 'runner'):
            asyncio.run(service(args))
            return 0
        from cursus.http import request_local
        if args.command == 'status':
            route = '/'
            if args.deployment:
                route = '/deployment'
            elif args.phase_id:
                route = '/phases/' + validate('Id', args.phase_id)
            elif args.attempt_id:
                route = '/attempts/' + validate('Id', args.attempt_id)
            result = request_local(args.socket, route)
        else:
            if args.input == '-':
                raw = sys.stdin.buffer.read(1048577)
            else:
                with __import__('pathlib').Path(args.input).open('rb') as source:
                    raw = source.read(1048577)
            value = decode_json(raw)
            if args.command == 'submit':
                value = {'kind': 'submit', 'input': validate('Input', value)}
            value = validate('Action', value)
            key = validate('Id', args.idempotency_key or str(uuid4()))
            result = request_local(args.socket, '/operator/actions', value, key)
            result = dict(result, request_id=key)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Problem as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(json.dumps({'code': 'unavailable', 'message': 'Configuration, input or service unavailable.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
