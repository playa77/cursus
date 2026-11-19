"""Control-side runner protocol, delegated by Control inside Store transactions."""

from datetime import datetime, timezone
from hashlib import sha256
from cursus.contracts import Problem, canonical_json, validate, _object, _enum, _integer
from cursus.store import payload


def now():
    return datetime.now(timezone.utc).isoformat()


async def request(control, runner_id, route, data, generation, request_id):
    if runner_id != control.settings['runner']['id']:
        raise Problem('forbidden', 'Runner is not enrolled.')
    validate('Id', generation)
    async def transition(tx):
        runner = await tx.get('runners', runner_id)
        if runner and runner['generation'] != generation:
            raise Problem('state_conflict', 'Runner generation changed; explicit recovery required.')
        if runner is None:
            runner = {'id': runner_id, 'generation': generation, 'reconciled': False}
        runner['last_contact'] = now()
        await tx.save('runners', runner)
        if route == f'runners/{runner_id}/reconcile':
            _object(data, {'generation', 'observations', 'pending_request_ids'})
            if data['generation'] != generation:
                raise Problem('state_conflict', 'Generation mismatch.')
            if not isinstance(data['observations'], list) or not isinstance(data['pending_request_ids'], list):
                raise Problem('invalid_contract', 'Expected recovery arrays.')
            for key in data['pending_request_ids']:
                validate('Id', key)
            held = await tx.connection.fetch('SELECT payload FROM attempts WHERE runner_id=$1 '
                                             "AND status IN ('active','unknown')", runner_id)
            held = [payload(row) for row in held]
            observed = {}
            for item in data['observations']:
                _object(item, {'attempt_id', 'kind', 'reason'}, {'terminal_seq'})
                validate('Id', item['attempt_id'])
                _enum(item['kind'], ('never_started', 'live', 'terminal_pending', 'stopped', 'unknown'))
                if item['attempt_id'] in observed:
                    raise Problem('invalid_contract', 'Duplicate observation.')
                observed[item['attempt_id']] = item
            known = {a['id'] for a in held}
            # Pending grant requests permit a lost response to be recovered. No
            # elapsed-time rule releases ownership or authorizes a relaunch.
            missing = [a for a in held if a['id'] not in observed
                       and a['claim']['request_id'] not in data['pending_request_ids']]
            runner['reconciled'] = not missing
            await tx.save('runners', runner)
            return {'held_claims': [a['claim'] for a in held], 'commands': [],
                    'ack_by_attempt': {a['id']: a['ack'] for a in held},
                    'reconciled': runner['reconciled'],
                    'dispositions': {a['id']: 'await-reconciliation' if a in missing else 'replay' for a in held}}
        if route == f'runners/{runner_id}/heartbeat':
            _object(data, {'slots', 'spool_bytes', 'boot_id', 'health'})
            _object(data['slots'], {'worker', 'verifier', 'frontier', 'repository'})
            for value in data['slots'].values():
                _integer(value, 0)
            _integer(data['spool_bytes'], 0)
            runner['health'] = data
            await tx.save('runners', runner)
            return {'held_claims': [], 'commands': [], 'ack_by_attempt': {},
                    'reconciled': runner['reconciled'], 'dispositions': {}}
        if route == 'jobs/next':
            _object(data, {'slot'})
            _enum(data['slot'], ('worker', 'verifier', 'frontier', 'repository'))
            if not runner['reconciled']:
                raise Problem('state_conflict', 'Reconcile before claiming.')
            if await tx.connection.fetchval('SELECT drain FROM coordination'):
                return None
            old = await tx.connection.fetchrow('SELECT payload FROM attempts WHERE runner_id=$1 '
                                               'AND request_id=$2', runner_id, request_id)
            if old:
                return {'runner_id': runner_id, 'claim': payload(old)['claim']}
            job_row = await tx.connection.fetchrow("SELECT id,payload FROM jobs WHERE state='queued' "
                                                   'AND slot=$1 ORDER BY creation_cursor,id '
                                                   'FOR UPDATE SKIP LOCKED LIMIT 1', data['slot'])
            if not job_row:
                return None
            from cursus.control import identity
            job, attempt_id = payload(job_row), identity()
            claim = {'job': job, 'attempt_id': attempt_id, 'runner_id': runner_id, 'request_id': request_id}
            attempt = {'id': attempt_id, 'claim': claim, 'ack': 0, 'status': 'active'}
            await tx.save('attempts', attempt, job_id=job['id'], phase_id=job['phase_id'],
                          runner_id=runner_id, request_id=request_id, status='active', ack=0)
            await tx.connection.execute("UPDATE jobs SET state='claimed' WHERE id=$1", job['id'])
            await tx.event(job['phase_id'], 'claimed', {'job_id': job['id'], 'attempt_id': attempt_id})
            return {'runner_id': runner_id, 'claim': claim}
        parts = route.split('/')
        if len(parts) == 3 and parts[0] == 'attempts' and parts[2] == 'events':
            attempt_id = validate('Id', parts[1])
            attempt = await tx.get('attempts', attempt_id)
            if not attempt or attempt['claim']['runner_id'] != runner_id:
                raise Problem('not_found', 'Attempt unavailable.')
            if not isinstance(data, list) or not 1 <= len(data) <= 100:
                raise Problem('invalid_contract', 'Expected a bounded event array.')
            for event in data:
                _object(event, {'attempt_id', 'seq', 'kind', 'payload'})
                if event['attempt_id'] != attempt_id:
                    raise Problem('invalid_contract', 'Foreign event attempt.')
                seq = validate('Seq', event['seq'])
                _enum(event['kind'], ('started', 'log', 'usage', 'final'))
                digest = sha256(canonical_json(event)).hexdigest()
                if seq <= attempt['ack']:
                    previous = await tx.connection.fetchval('SELECT digest FROM events WHERE attempt_id=$1 '
                                                             'AND source_seq=$2', attempt_id, seq)
                    if previous != digest:
                        raise Problem('sequence_conflict', 'Repeated event differs.')
                    continue
                if seq != attempt['ack'] + 1:
                    raise Problem('sequence_conflict', f"Next expected sequence is {attempt['ack'] + 1}.")
                if attempt['status'] != 'active':
                    raise Problem('state_conflict', 'Attempt is terminal.')
                if event['kind'] == 'log' and len(canonical_json(event['payload'])) > 65536:
                    raise Problem('payload_too_large', 'Log event exceeds limit.')
                if event['kind'] == 'final':
                    await control.completed(tx, attempt, event['payload'])
                await tx.event(attempt['claim']['job']['phase_id'], event['kind'], event,
                               attempt_id, seq)
                attempt['ack'] = seq
            await tx.save('attempts', attempt, ack=attempt['ack'], status=attempt['status'])
            return {'committed_through': attempt['ack'], 'next_expected': attempt['ack'] + 1,
                    'disposition': 'active' if attempt['status'] == 'active' else 'terminal'}
        raise Problem('not_found', 'Runner route unavailable.')
    return await control.store.transact(runner_id, route, request_id, data, transition)
