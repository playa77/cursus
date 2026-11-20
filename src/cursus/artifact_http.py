"""Bounded binary routes shared by the authorized operator and runner ingress."""
import re
import asyncio
from urllib.parse import quote, unquote
from fastapi import Request
from fastapi.responses import StreamingResponse
from cursus.contracts import Problem, validate
from cursus.artifact_control import upload, download


def one(request, key):
    values = request.headers.getlist(key)
    if len(values) != 1:
        raise Problem('invalid_fields', 'One ' + key + ' is required.')
    return values[0]


def mount(app, control, local):
    if not local:
        @app.put('/attempts/{attempt_id}/artifacts/{file_id}')
        async def ingest(request: Request, attempt_id: str, file_id: str):
            validate('Id', one(request, 'idempotency-key'))
            generation = validate('Id', one(request, 'x-cursus-generation'))
            length = one(request, 'content-length')
            if not re.fullmatch(r'0|[1-9][0-9]{0,9}', length):
                raise Problem('invalid_scalar', 'Invalid artifact length.')
            name = one(request, 'x-cursus-file-name')
            if re.search(r'%(?![0-9a-fA-F]{2})', name):
                raise Problem('invalid_path', 'Invalid encoded filename.')
            try:
                name = unquote(name, errors='strict')
            except UnicodeError:
                raise Problem('invalid_path', 'Invalid UTF-8 filename.') from None
            ref = dict(id=file_id, digest=one(request, 'x-cursus-sha256'), length=int(length),
                       name=name, media_type=one(request, 'content-type'))
            return await upload(control, control.settings['runner']['id'], generation,
                                attempt_id, ref, request.stream())

        @app.get('/runner/artifacts/{file_id}')
        async def runner_file(request: Request, file_id: str):
            if list(request.query_params) != ['claim_id'] or len(request.query_params.multi_items()) != 1:
                raise Problem('invalid_fields', 'One current claim_id is required.')
            row = await download(control, control.settings['runner']['id'], file_id,
                                 one(request, 'x-cursus-generation'), request.query_params['claim_id'])
            return await response(control, row)
    else:
        @app.get('/artifacts/{file_id}')
        async def operator_file(file_id: str):
            return await response(control, await download(control, 'local_operator', file_id))


async def response(control, row):
    ref = row['file']
    source = await asyncio.to_thread(control.artifacts.open,row['attempt_id'],ref)
    def chunks():
        try:
            while raw := source.read(65536):
                yield raw
        finally:
            source.close()
    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
        'Content-Length': str(ref['length']), 'X-Cursus-Sha256': ref['digest'],
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(ref['name'], safe=''),
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})
