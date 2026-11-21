"""Sole infrastructure composition root and offline-discoverable entry points."""

import argparse
import asyncio
import json
import sys
from uuid import uuid4
from cursus import __version__
from cursus.contracts import Problem, decode_json, validate


def default_socket():
    import os
    return (os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}') + '/cursus/operator.sock'


def parser():
    root = argparse.ArgumentParser(prog='cursus', description='Private evidence-driven work coordination.')
    root.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = root.add_subparsers(dest='command')
    command = commands.add_parser('serve', help='run the control plane and the runner in one process')
    command.add_argument('--config', required=True)
    command = commands.add_parser('preflight', help='check installed native CLIs (version/help only; no login, no inference)')
    command.add_argument('--roles', required=True, help='roles.toml naming the CLIs this deployment uses')
    command.add_argument('--config', help='service config; only its [execution] section is read')
    for name in ('submit', 'action', 'status'):
        command = commands.add_parser(name)
        command.add_argument('--socket', default=default_socket(), help='operator socket (default: your runtime directory)')
        if name == 'status':
            selection = command.add_mutually_exclusive_group()
            selection.add_argument('--phase-id')
            selection.add_argument('--attempt-id')
            selection.add_argument('--deployment', action='store_true')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--idempotency-key')
    return root


def preflight(args):
    """Operator check that each CLI the roles use is installed. Signed-in state is NOT checked."""
    import os
    import tomllib
    from pathlib import Path
    from cursus.config import execution_environment
    from cursus.host import DEFAULT_PATH
    from cursus.recipes import preflight as check, resolve
    roles = tomllib.loads(Path(args.roles).read_text()).get('roles', {})
    required = sorted({role['cli'] for role in roles.values()})
    if args.config:
        settings = tomllib.loads(Path(args.config).read_text()).get('execution', {})
        execution_environment(settings)  # Reserves are not needed to locate the CLIs.
    else:
        search = [d for d in os.environ.get('PATH', DEFAULT_PATH).split(':') if d.startswith('/')]
        settings = {'path': ':'.join(search) or DEFAULT_PATH}
        print('No --config: using your current PATH. Set [execution] path or clis for the service.')
    print(f'Checking {len(required)} CLI(s) used by the roles: {", ".join(required)}. '
          'Version and help queries only; sign-in is not checked.')
    failures = 0
    for cli in required:
        binary = resolve(cli, settings)
        if binary is None:
            print(f'FAIL {cli}: not found. Install it and sign in as this user, then list its directory in [execution] path.')
            failures += 1
            continue
        result = asyncio.run(check(cli, binary, settings))
        if result['ok']:
            print(f'ok   {cli}: {binary} ({result["version"] or "version unknown"})')
        else:
            failures += 1
            reason = result.get('error') or 'missing options: ' + ', '.join(result['missing'])
            print(f'FAIL {cli}: {binary} ({result["version"] or "version unknown"}): {reason}')
    print('Preflight ' + ('passed.' if not failures else f'failed for {failures} CLI(s).') +
          ' Signing in remains your responsibility; a signed-out CLI fails on first use.')
    return 1 if failures else 0


def check_identity(settings):
    """The service must run as the non-root user whose CLI logins it uses (ADR 0016)."""
    import os
    import pwd
    if os.geteuid() == 0:
        raise Problem('identity_boundary', 'Run as the non-root user whose CLI logins Cursus uses.')
    account = pwd.getpwnam(settings['service']['user'])
    if (account.pw_uid, account.pw_gid) != (os.getuid(), os.getgid()):
        raise Problem('identity_boundary', 'The running user differs from service.user.')


async def service(args):
    import logging
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    from cursus.config import load
    settings = load('serve', args.config)
    check_identity(settings)
    return await run(settings)


async def run(settings, github=None, admin=None):
    """Control plane, runner and HTTP surfaces in one supervised process.

    Any component ending, normally or not, ends the process; a supervisor restarts
    it and the runner reconciles from its journal and the database. `github` is a
    test seam for the publication client; production builds the real one.
    """
    import asyncpg
    import logging
    from cursus.artifacts import Artifacts
    from cursus.browser import environment
    from cursus.control import Control
    from cursus.execution import Execution
    from cursus.host import HostRuntime
    from cursus.http import serve
    from cursus.recipes import discover
    from cursus.repository import GitHub, Repository
    from cursus.runner import Journal, LocalTransport, Runner
    from cursus.store import Store
    service = settings['service']
    pool = await asyncpg.create_pool(settings['dsn'], min_size=1, max_size=10)
    try:
        store = Store(pool)
        await store.migrate()
        control = Control(settings, store, artifacts=Artifacts(service['artifact_root']))
        restart = asyncio.Event()
        control.admin = admin if admin is not None else make_admin(settings)
        if control.admin:
            loop = asyncio.get_running_loop()
            control.admin.restart_hook = lambda: loop.call_soon_threadsafe(restart.set)
        await control.maintain('boot')
        journal = Journal(service['state_root'], settings['limits']['spool_bytes'])
        try:
            publisher = settings['publisher']
            enrollment = {(r['owner'], r['name']): r for r in settings['repositories']}
            repository = Repository(service['repository_root'], service['worktree_root'], service['review_root'],
                enrollment, github or GitHub(publisher['github_credential_file']), publisher['git_binary'],
                publisher['git_credential_file'])
            runtime = HostRuntime(settings['execution'], journal.root / 'execution', settings['capacity'])
            await runtime.preflight()
            clis = discover(settings['execution'])
            logging.getLogger('cursus.runner').info(json.dumps({'event': 'clis_resolved', 'clis': clis,
                'missing': sorted({'pi', 'claude', 'codex', 'agy'} - set(clis))}))
            runner_id = settings['runner']['id']
            runner = Runner(runner_id, journal, LocalTransport(control, runner_id, journal.generation),
                            repository, Execution(clis, runtime))
            async def maintenance():
                while True:
                    await asyncio.sleep(settings['limits']['heartbeat_seconds'])
                    await control.maintain('tick')
            async def restart_requested():
                await restart.wait()
                await asyncio.sleep(1)  # Let the response that asked for it reach the browser.
            tasks = [asyncio.create_task(maintenance(), name='maintenance'),
                     asyncio.create_task(restart_requested(), name='restart'),
                     asyncio.create_task(serve(settings, control, environment()), name='http'),
                     asyncio.create_task(runner.serve(), name='runner')]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            journal.close()
    finally:
        await pool.close()
    from cursus.admin import RESTART_EXIT_STATUS
    return RESTART_EXIT_STATUS if control.admin and control.admin.restart_requested else 0


def make_admin(settings):
    from cursus.admin import Admin
    return Admin(settings) if settings.get('_config') else None


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    if not args.command:
        root.print_help()
        return 0
    try:
        if args.command == 'serve':
            return asyncio.run(service(args))
        if args.command == 'preflight':
            return preflight(args)
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
