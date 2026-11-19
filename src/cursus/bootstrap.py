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
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--idempotency-key')
    return root


async def service(args):
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
            control = Control(settings, store)
            if hasattr(control, 'maintain'):
                await control.maintain('boot')
            await serve(settings, control)
        finally:
            await pool.close()
    else:
        from cursus.runner import compose
        await compose(settings)


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
            if args.phase_id:
                route = '/phases/' + validate('Id', args.phase_id)
            elif args.attempt_id:
                route = '/attempts/' + validate('Id', args.attempt_id)
            result = request_local(args.socket, route)
        else:
            raw = sys.stdin.buffer.read(1048577) if args.input == '-' else __import__('pathlib').Path(args.input).read_bytes()
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
