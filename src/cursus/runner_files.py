"""Runner-owned evidence spool and transfer, retained across upload failures."""
from hashlib import sha256
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid5
from urllib.parse import quote
from cursus.contracts import Problem, canonical_json, validate
from cursus.artifacts import MAX_FILE


def evidence(runner, attempt_id, value):
    raw = canonical_json(value) + b'\n'
    if len(raw) > MAX_FILE:
        raise Problem('payload_too_large', 'Verifier evidence exceeds file budget.')
    used = runner.journal.path.stat().st_size + sum(p.stat().st_size for p in runner.journal.root.glob('evidence-*') if p.is_file())
    if used + len(raw) + 65536 > runner.journal.max_bytes or shutil.disk_usage(runner.journal.root).free < len(raw) + 65536:
        raise Problem('storage', 'Evidence spool reserve exhausted.')
    file_id = str(uuid5(UUID(attempt_id), 'verification-evidence'))
    path = runner.journal.root / ('evidence-' + file_id)
    temporary = path.with_suffix('.tmp')
    with temporary.open('xb') as output:
        os.chmod(temporary, 0o600)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    ref = dict(id=file_id, digest=sha256(raw).hexdigest(), length=len(raw),
               name='verification-evidence.json', media_type='application/json')
    runner.record('artifact_pending', dict(attempt_id=attempt_id, file=ref, path=str(path)))
    return [dict(item, log=ref) for item in value]


async def replay(runner):
    receipts = {r['value']['id'] for r in runner.journal.records if r['kind'] in ('artifact_receipt','artifact_discarded')}
    directives = [r['value'] for r in runner.journal.records if r['kind']=='directive']
    dispositions = directives[-1].get('dispositions',{}) if directives else {}
    for record in list(runner.journal.records):
        if record['kind'] != 'artifact_pending' or record['value']['file']['id'] in receipts:
            continue
        item = record['value']
        if dispositions.get(item['attempt_id']) in ('stop-stale','ignore-stale'):
            runner.record('artifact_discarded', dict(id=item['file']['id'], reason='Reconciled stale attempt.'))
            receipts.add(item['file']['id'])
            continue
        result = await runner.transport.upload(item['attempt_id'], item['file'], Path(item['path']))
        if validate('FileRef', result) != item['file']:
            raise Problem('artifact_conflict', 'Upload receipt differs from evidence.')
        runner.record('artifact_receipt', result)
        receipts.add(result['id'])


def headers(ref):
    return {'Content-Type': ref['media_type'], 'Content-Length': str(ref['length']),
            'X-Cursus-Sha256': ref['digest'], 'X-Cursus-File-Name': quote(ref['name'], safe='')}


def checked_bytes(ref, raw):
    validate('FileRef', ref)
    if len(raw) != ref['length'] or sha256(raw).hexdigest() != ref['digest']:
        raise Problem('artifact_conflict', 'Downloaded bytes differ.')
    return raw
