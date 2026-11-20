"""Claim-scoped artifact admission; no filesystem IO inside database transactions."""
from uuid import uuid4
from cursus.contracts import Problem, validate
from cursus.artifacts import MAX_FILE, MAX_PHASE


def file_refs(value):
    if isinstance(value, dict):
        if set(value) == {'id', 'digest', 'length', 'name', 'media_type'}:
            yield validate('FileRef', value)
        else:
            for child in value.values():
                yield from file_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from file_refs(child)


async def owner(tx, runner_id, generation, attempt_id):
    runner = await tx.get('runners', runner_id)
    attempt = await tx.get('attempts', attempt_id)
    if (not runner or runner['generation'] != generation or not runner['reconciled'] or
            not attempt or attempt['claim']['runner_id'] != runner_id or
            attempt['status'] != 'active'):
        raise Problem('forbidden', 'A current reconciled claim is required.')
    return attempt


async def upload(control, runner_id, generation, attempt_id, ref, stream):
    validate('Id', attempt_id)
    validate('FileRef', ref)
    if not control.artifacts:
        raise Problem('unavailable', 'Artifact storage unavailable.')
    if ref['length'] > MAX_FILE:
        raise Problem('payload_too_large', 'Artifact exceeds 32 MiB.')
    async def reserve(tx):
        attempt = await owner(tx, runner_id, generation, attempt_id)
        existing = await tx.get('artifacts', ref['id'])
        if existing:
            if existing['attempt_id'] != attempt_id or existing['file'] != ref:
                raise Problem('artifact_conflict', 'Artifact identity has different metadata.')
            return existing
        phase_id = attempt['claim']['job']['phase_id']
        total = await tx.connection.fetchval(
            "SELECT coalesce(sum((payload->'file'->>'length')::bigint),0) FROM artifacts "
            "WHERE payload->>'phase_id'=$1", phase_id)
        if total + ref['length'] > MAX_PHASE:
            raise Problem('payload_too_large', 'Phase artifact budget exhausted.')
        row = dict(id=ref['id'], attempt_id=attempt_id, phase_id=phase_id, file=ref, state='staged')
        await tx.save('artifacts', row, attempt_id=attempt_id)
        return row
    await control.store.transact(runner_id, 'artifact/reserve', str(uuid4()), ref, reserve)
    await control.artifacts.stage(attempt_id, ref, stream)
    async def ready(tx):
        await owner(tx, runner_id, generation, attempt_id)
        row = await tx.get('artifacts', ref['id'])
        if row['state'] != 'ready':
            row['state'] = 'ready'
            await tx.save('artifacts', row)
            await tx.event(row['phase_id'], 'artifact_ready', {'file': ref})
        return ref
    return await control.store.transact(runner_id, 'artifact/ready', str(uuid4()), ref, ready)


async def download(control, principal, file_id, generation=None, claim_id=None):
    validate('Id', file_id)
    if principal != 'local_operator' and principal != control.settings['runner']['id']:
        raise Problem('forbidden', 'Artifact authorization required.')
    async def authorize(tx):
        row = await tx.get('artifacts', file_id)
        if not row or row['state'] != 'ready' or not await tx.get('phases', row['phase_id']):
            raise Problem('not_found', 'Artifact unavailable.')
        if principal != 'local_operator':
            validate('Id', claim_id)
            attempt = await owner(tx, principal, generation, claim_id)
            if row['file'] not in list(file_refs(attempt['claim']['job']['input'])):
                raise Problem('forbidden', 'Artifact is not a declared claim input.')
        return row
    return await control.store.transact(principal, 'artifact/read', str(uuid4()), {}, authorize)


async def verify_ready(tx, attempt, value):
    for item in value:
        ref = validate('FileRef', item.get('log'))
        row = await tx.get('artifacts', ref['id'])
        if not row or row['state'] != 'ready' or row['attempt_id'] != attempt['id'] or row['file'] != ref:
            raise Problem('invalid_evidence', 'Verifier log is not committed and ready.')
