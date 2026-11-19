"""Durable operator recovery and original-attempt command ownership."""
from cursus.contracts import Problem
from cursus.store import payload


async def command(tx, attempt, action, **data):
    from cursus.control import identity
    item = dict(id=identity(), attempt_id=attempt['id'], action=action,
                issued_seq=tx.cursor + 1, state='pending', **data)
    await tx.event(attempt['claim']['job']['phase_id'], 'command', item)
    await tx.save('commands', item, attempt_id=attempt['id'], issued_seq=item['issued_seq'])
    attempt.setdefault('commands',{})[item['id']]=item
    await tx.save('attempts',attempt)
    return item


async def commands(tx, runner_id):
    rows = await tx.connection.fetch('SELECT c.payload FROM commands c JOIN attempts a ON c.attempt_id=a.id '
        "WHERE a.runner_id=$1 AND a.status IN ('active','unknown') AND c.payload->>'state'='pending' "
        'ORDER BY c.issued_seq', runner_id)
    return [{k:v for k,v in payload(r).items() if k != 'state'} for r in rows]


async def retry(control, tx, attempt, reason):
    job = attempt['claim']['job']
    phase = await tx.get('phases', job['phase_id'])
    count = job.get('interrupted_count', 0)
    if phase['state'] == 'canceling':
        return
    if count >= control.settings['limits'].get('interrupted_retries', 2):
        phase.update(state='parked', reason='Interrupted-step retry budget exhausted.')
    else:
        phase.update(state='execution', reason=reason)
        if job['step']=='debug':
            for key in ('debug_checkpoint','debug_passed','debug_evidence','debug_reproduced'):
                phase.pop(key,None)
        extra = {k:v for k,v in job.items() if k not in ('id','phase_id','step','slot','input','invocation')}
        role = job.get('invocation', {}).get('role', {}).get('name')
        extra['interrupted_count'] = count + 1
        await control.enqueue(tx, phase, job['step'], job['slot'], job['input'], role=role, **extra)
    await tx.save('phases', phase)


async def action(control, tx, value):
    kind = value['kind']
    if kind == 'cancel':
        phase = await tx.get('phases', value['phase_id'])
        if not phase or phase['state'] in ('delivered','canceled'):
            raise Problem('state_conflict', 'Phase cannot be canceled.')
        await tx.connection.execute("UPDATE jobs SET state='canceled' WHERE phase_id=$1 AND state='queued'", phase['id'])
        rows = await tx.connection.fetch("SELECT payload FROM attempts WHERE phase_id=$1 AND status IN ('active','unknown')",phase['id'])
        for row in rows:
            await command(tx,payload(row),'stop')
        pending = await tx.connection.fetchval("SELECT count(*) FROM publications WHERE phase_id=$1 AND state='pending'",phase['id'])
        phase['state'] = 'canceling' if rows or pending else 'canceled'
    else:
        attempt = await tx.get('attempts', value['attempt_id'])
        if not attempt:
            raise Problem('not_found', 'Attempt unavailable.')
        phase = await tx.get('phases', attempt['claim']['job']['phase_id'])
        if kind == 'steer':
            if attempt['status'] != 'active' or attempt['claim']['job']['step'] not in ('produce','debug'):
                raise Problem('state_conflict', 'Only an active pi execution accepts steering.')
            await command(tx, attempt, 'steer', text=value['text'])
        elif kind == 'declare_unrecoverable':
            if attempt['status'] not in ('active','unknown'):
                raise Problem('state_conflict','Only held attempts can become unknown.')
            attempt.update(status='unknown', reason=value['reason'])
            phase.update(state='parked', reason=value['reason'])
            await tx.save('attempts',attempt,status='unknown')
        elif kind == 'abandon':
            if attempt['status'] != 'unknown' or phase['state'] != 'parked':
                raise Problem('state_conflict','Only a parked unknown attempt can be abandoned.')
            if attempt['claim']['job'].get('publication_id'):
                raise Problem('state_conflict','Reconcile remote publication before abandonment.')
            attempt.update(status='abandoned',reason=value['reason'])
            await tx.save('attempts',attempt,status='abandoned')
            await tx.connection.execute("UPDATE jobs SET state='done' WHERE id=$1",attempt['claim']['job']['id'])
            await tx.connection.execute("UPDATE jobs SET state='canceled' WHERE state='queued' AND payload->'input'->>'debug_attempt_id'=$1",attempt['id'])
            await retry(control,tx,attempt,value['reason'])
            phase = await tx.get('phases', phase['id'])
        else:
            raise Problem('invalid_variant','Unsupported recovery action.')
    phase['revision'] += 1
    await tx.save('phases', phase)
    await tx.event(phase['id'], kind, value)
    return dict(entity_id=phase['id'],state=phase['state'],revision=phase['revision'],cursor=tx.cursor)


async def result(tx, attempt, value):
    item = await tx.get('commands', value['command_id'])
    if not item or item['attempt_id'] != attempt['id']:
        raise Problem('state_conflict','Command belongs to another attempt.')
    if item['state'] != 'pending' and item.get('result') != value:
        raise Problem('state_conflict','Command outcome differs.')
    item.update(state=value['disposition'],result=value)
    await tx.save('commands',item)
    attempt.setdefault('commands',{})[item['id']]=item
