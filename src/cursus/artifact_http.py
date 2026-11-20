"""Operator artifact download; the runner uses artifact_control directly in-process."""
from urllib.parse import quote
from fastapi.responses import StreamingResponse
from cursus.artifact_control import download


def mount(app, control, local):
    if local:
        @app.get('/artifacts/{file_id}')
        async def operator_file(file_id: str):
            return response(control, await download(control, 'local_operator', file_id))


def response(control, row):
    ref = row['file']
    source = control.artifacts.open(row['attempt_id'], ref)
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
