"""Unix operator socket and loopback browser surfaces; the runner is in-process (ADR 0016)."""

import asyncio
import grp
import http.client
import os
from pathlib import Path
import socket
import signal
from contextlib import nullcontext

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from cursus.contracts import Problem, decode_json, canonical_json, validate, MAX_REQUEST_BYTES


def application(control, local=False, browser=False, templates=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    browser_surface = None

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        code = 409 if exc.code in ('idempotency_conflict', 'sequence_conflict', 'state_conflict', 'artifact_conflict') else 422
        code = {'forbidden': 403, 'unauthorized': 401, 'not_found': 404,
                'payload_too_large': 413, 'unavailable': 503}.get(exc.code, code)
        if browser_surface:
            return browser_surface.render(request, 'problem.html', status=code, problem=exc.as_dict(), title='Problem')
        return JSONResponse(exc.as_dict(), status_code=code, headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def guard(request, call_next):
        # Authentication happens before payload decoding, including failures.
        if browser_surface:
            try:
                browser_surface.authorize(request)
            except Problem as exc:
                return await problem_handler(request, exc)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if browser_surface:
            response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        return response

    async def body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise Problem('invalid_contract', 'JSON Content-Type is required.')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_REQUEST_BYTES:
                raise Problem('payload_too_large', 'Request exceeds byte limit.')
        return decode_json(bytes(data))

    def request_id(request):
        values = request.headers.getlist('idempotency-key')
        if len(values) != 1:
            raise Problem('invalid_fields', 'One Idempotency-Key is required.')
        return validate('Id', values[0])

    from cursus.artifact_http import mount
    mount(app, control, local)

    if browser:
        from cursus.browser import mount as mount_browser
        browser_surface = mount_browser(app, control, templates)

    if local:
        @app.post('/operator/actions')
        async def action(request: Request):
            return await control.action('local_operator', request_id(request), await body(request))

        @app.get('/phases/{entity_id}')
        async def phase(entity_id: str):
            return await control.query('local_operator', 'phases', entity_id)

        @app.get('/attempts/{entity_id}')
        async def attempt(entity_id: str):
            return await control.query('local_operator', 'attempts', entity_id)

        @app.get('/deployment')
        async def deployment():
            return await control.query('local_operator', 'deployment')

        @app.get('/')
        async def overview():
            return await control.query('local_operator', 'overview')
    return app


async def serve(settings, control, templates=None):
    service = settings['service']
    path = Path(service['operator_socket'])
    # Do not unlink an unknown pre-existing socket or change its ownership.
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unix.bind(str(path))
    os.chown(path, -1, grp.getgrnam(service['operator_group']).gr_gid)
    os.chmod(path, 0o660)
    unix.listen(128)
    unix.setblocking(False)
    configs = [uvicorn.Config(application(control, True), log_level='warning'),
               uvicorn.Config(application(control, browser=True, templates=templates), host=service['listen_host'],
                              port=service['listen_port'], log_level='warning')]
    servers = [uvicorn.Server(item) for item in configs]
    loop = asyncio.get_running_loop()
    def stop():
        for server in servers:
            server.should_exit = True
    for server in servers:
        server.capture_signals = nullcontext
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop)
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(servers[0].serve(sockets=[unix]))
            tasks.create_task(servers[1].serve())
    finally:
        stop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)
        unix.close()
        path.unlink(missing_ok=True)


class LocalConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=35)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def request_local(socket_path, route, action=None, request_id=None):
    connection = LocalConnection(socket_path)
    try:
        headers = {'Content-Type': 'application/json'}
        if request_id:
            headers['Idempotency-Key'] = request_id
        connection.request('POST' if action is not None else 'GET', route,
                           canonical_json(action) if action is not None else None, headers)
        response = connection.getresponse()
        result = decode_json(response.read(MAX_REQUEST_BYTES + 1))
        if response.status >= 400:
            raise Problem(**result)
        return result
    finally:
        connection.close()
