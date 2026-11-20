"""Server-rendered operator surface; all mutations use the existing Control seam."""
import anyio
from hashlib import sha256
import hmac
from importlib.resources import files
import secrets
import time
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from cursus.contracts import Problem, canonical_json, decode_json, validate, MAX_REQUEST_BYTES
from cursus.artifact_control import download
from cursus.artifact_http import response as file_response

COOKIE = '__Host-cursus_session'


def environment():
    return Environment(loader=PackageLoader('cursus', 'templates'),
                       autoescape=select_autoescape(('html',)))


class Browser:
    def __init__(self, control, templates):
        self.control, self.templates = control, templates
        self.key = secrets.token_bytes(32)
        self.origin = control.settings['service']['external_origin']

    def csrf(self, request):
        token = request.cookies.get(COOKIE, '')
        try:
            issued, nonce, signature = token.split('.')
            signed = issued + '.' + nonce
            valid = (0 <= time.time() - int(issued) < 28800 and len(nonce) == 64 and
                     hmac.compare_digest(signature, hmac.new(self.key, signed.encode(), sha256).hexdigest()))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            signed = str(int(time.time())) + '.' + secrets.token_hex(32)
            token = signed + '.' + hmac.new(self.key, signed.encode(), sha256).hexdigest()
        return token, valid

    def authorize(self, request):
        if request.headers.getlist('tailscale-user-login') != [self.control.settings['service']['operator_login']]:
            raise Problem('forbidden', 'Operator Serve identity required.')
        if request.headers.getlist('host') != [urlsplit(self.origin).netloc]:
            raise Problem('forbidden', 'Configured host required.')
        if request.method == 'POST' and request.headers.getlist('origin') != [self.origin]:
            raise Problem('forbidden', 'Exact browser Origin required.')

    def render(self, request, template, status=200, **context):
        token, _ = self.csrf(request)
        context.update(csrf=token, request_id=lambda: str(uuid4()),
            login=self.control.settings['service']['operator_login'],
            theme=request.cookies.get('cursus_theme', 'system'),
            title=context.get('title', 'Cursus'), view=context.get('view', {}))
        result = HTMLResponse(self.templates.get_template(template).render(**context), status_code=status)
        result.set_cookie(COOKIE, token, max_age=28800, secure=True, httponly=True, samesite='strict', path='/')
        return result

    async def page(self, request, route, identity=None):
        view = await self.control.query('local_operator', 'browser/' + route, identity)
        phase = view['phase']
        attempt = view['entity'] if route == 'attempts' else None
        ready = [row['file'] for row in view['artifacts'] if row['state'] == 'ready'] if phase else []
        # All values are committed; unreported usage remains explicitly unknown.
        runner = next(iter(view['runners']), {})
        health = runner.get('health', {})
        jobs = view['jobs']
        metrics = dict(slots=health.get('slots'), queued=view['queue_counts'].get('queued',0),
            claimed=view['queue_counts'].get('claimed',0), usage=reported_usage(view['usage']), runner=runner,
            spool=health.get('spool_bytes', 'unknown'))
        return self.render(request, {'overview':'index.html','phases':'phase.html','attempts':'attempt.html'}[route],
            view=view, phase=phase, attempt=attempt, files=ready, metrics=metrics,
            title=('New run & intake' if request.query_params.get('new')=='1' else 'Attempts' if request.query_params.get('attempts')=='1' else 'Overview') if route=='overview' else ('Attempt' if attempt else 'Phase'),
            intake=request.query_params.get('new') == '1', attempts_page=request.query_params.get('attempts') == '1',
            repositories=self.control.settings['repositories'])

    async def action(self, request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_REQUEST_BYTES:
                raise Problem('payload_too_large', 'Request exceeds byte limit.')
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise Problem('invalid_contract', 'URL-encoded browser form required.')
        try:
            fields = parse_qsl(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=30, errors='strict')
        except (ValueError, UnicodeError):
            raise Problem('invalid_contract', 'Invalid form encoding.') from None
        data = dict(fields)
        if len(data) != len(fields):
            raise Problem('invalid_fields', 'Duplicate form field.')
        token, valid = self.csrf(request)
        submitted = data.pop('csrf', '')
        if not valid or not submitted.isascii() or not hmac.compare_digest(submitted, token):
            raise Problem('forbidden', 'Valid session and CSRF token required.')
        key = validate('Id', data.pop('request_id', None))
        value = form_action(data)
        reply = await self.control.action('local_operator', key, value)
        target = '/phases/' + reply['entity_id']
        if request.headers.get('hx-request') == 'true':
            return HTMLResponse('', headers={'HX-Redirect': target})
        return RedirectResponse(target, status_code=303)

    async def events(self, request, entity_id):
        await self.control.query('local_operator', 'phases', entity_id)
        ids = request.headers.getlist('last-event-id')
        pairs = request.query_params.multi_items()
        if len(ids)>1 or len(pairs)>1 or any(k!='cursor' for k,_ in pairs):
            raise Problem('invalid_fields', 'One event cursor required.')
        raw = ids[0] if ids else request.query_params.get('cursor', '0')
        if not raw.isascii() or not raw.isdigit() or len(raw)>18:
            raise Problem('invalid_scalar', 'Invalid event cursor.')
        cursor = int(raw)
        async def stream():
            nonlocal cursor
            keepalive = time.monotonic()
            while not await request.is_disconnected():
                # Finish short DB reads/listener cleanup if the client disconnects
                # inside Starlette's cancellation scope. Never strand a transaction.
                with anyio.CancelScope(shield=True):
                    page = await self.control.query('local_operator', 'events', entity_id, cursor)
                if page['reset']:
                    yield 'event: reset\ndata: {}\n\n'
                    return
                for event in page['items']:
                    cursor = event['cursor']
                    yield f'id: {cursor}\nevent: committed\ndata: {canonical_json(event).decode()}\n\n'
                if page['items']:
                    continue
                if time.monotonic()-keepalive >= 15:
                    yield ': keepalive\n\n'
                    keepalive = time.monotonic()
                with anyio.CancelScope(shield=True):
                    await self.control.wait(time.monotonic()+5, page['snapshot_cursor'])
        return StreamingResponse(stream(), media_type='text/event-stream', headers={
            'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})


def reported_usage(rows):
    from decimal import Decimal
    result = {}
    for field in ('input_tokens','output_tokens'):
        values = [r[field] for r in rows if field in r]
        result[field] = sum(values) if values else 'unknown'
    costs = {}
    for row in rows:
        if 'cost' in row:
            currency = row['currency']
            costs[currency] = costs.get(currency, Decimal(0)) + Decimal(row['cost'])
    result['costs'] = {key:str(value) for key,value in costs.items()}
    return result


def form_action(data):
    kind = data.get('kind')
    if kind != 'submit':
        return validate('Action', data)
    allowed = {'kind','workflow','form','source_kind','text','repository','source_owner',
               'source_name','source_commit','source_path','plan_debate','spec_debate'}
    if data.keys() - allowed:
        raise Problem('invalid_fields', 'Unsupported intake field.')
    try:
        owner, name, target = data['repository'].split('|')
        source = {'kind': data['source_kind']}
        if source['kind'] == 'inline':
            source['text'] = data.get('text', '')
        elif source['kind'] == 'repo':
            source.update(owner=data.get('source_owner',''),name=data.get('source_name',''),
                commit=data.get('source_commit',''),path=data.get('source_path',''))
        value = dict(workflow=data['workflow'], source=source,
            repo=dict(owner=owner,name=name,target_ref=target),
            plan_debate=data.get('plan_debate') == 'on', spec_debate=data.get('spec_debate') == 'on')
        if value['workflow'] == 'code':
            value['form'] = data.get('form','phase')
    except (KeyError, ValueError):
        raise Problem('invalid_fields', 'Incomplete intake form.') from None
    return validate('Action', dict(kind=kind, input=value))


def mount(app, control, templates=None):
    browser = Browser(control, templates or environment())
    app.state.browser = browser
    app.mount('/static', StaticFiles(directory=str(files('cursus').joinpath('static'))), name='static')

    @app.get('/')
    async def overview(request: Request):
        return await browser.page(request, 'overview')

    @app.get('/phases/{entity_id}')
    async def phase(request: Request, entity_id: str):
        return await browser.page(request, 'phases', entity_id)

    @app.get('/attempts/{entity_id}')
    async def attempt(request: Request, entity_id: str):
        return await browser.page(request, 'attempts', entity_id)

    @app.post('/operator/actions')
    async def action(request: Request):
        return await browser.action(request)

    @app.get('/phases/{entity_id}/events')
    async def events(request: Request, entity_id: str):
        return await browser.events(request, entity_id)

    @app.get('/artifacts/{file_id}')
    async def artifact(file_id: str):
        return file_response(control, await download(control, 'local_operator', file_id))
    return browser
