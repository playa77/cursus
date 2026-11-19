"""Sole coordination hub; no subprocess or external repository operations."""

from uuid import uuid4
from cursus.contracts import Problem, validate
from cursus import workflows


def identity():
    return str(uuid4())


class Control:
    def __init__(self, settings, store, decide=workflows.decide):
        self.settings, self.store, self.decide = settings, store, decide

    def enrolled(self, repo):
        for item in self.settings['repositories']:
            if (item['owner'], item['name']) == (repo['owner'], repo['name']):
                if repo['target_ref'] in item['allowed_target_refs']:
                    return item
        raise Problem('not_enrolled', 'Repository or target is not enrolled.')

    async def action(self, principal, request_id, value):
        if principal != 'local_operator':
            raise Problem('forbidden', 'Operator authorization required.')
        value = validate('Action', value)
        async def transition(tx):
            decision = self.decide({}, value)
            data = value['input']
            self.enrolled(data['repo'])
            source = data['source']
            if source['kind'] == 'repo':
                self.enrolled(dict(owner=source['owner'], name=source['name'],
                                   target_ref=data['repo']['target_ref']))
            phase_id = identity()
            phase = {'id': phase_id, 'input': data, 'state': decision['state'],
                     'revision': 1, 'roles': self.settings.get('roles', {}),
                     'registry_commit': self.settings['service'].get('role_release_commit'),
                     'profile_digest': self.settings.get('profile_digest'),
                     'references': []}
            await tx.save('phases', phase)
            await tx.revision('specs', phase_id, 1, source)
            await tx.event(phase_id, 'submitted', {'input': data})
            await self.enqueue(tx, phase, decision['step'], decision['slot'], decision['input'])
            return {'entity_id': phase_id, 'state': phase['state'], 'revision': 1, 'cursor': tx.cursor}
        return await self.store.transact(principal, 'operator/actions', request_id, value, transition)

    async def enqueue(self, tx, phase, step, slot, inputs, **extra):
        role_name = extra.pop('role', None)
        if role_name:
            from cursus.contracts import canonical_json
            role = phase['roles'].get(role_name)
            if role is None:
                raise Problem('invalid_config', 'Required role is unavailable.')
            extra['invocation'] = {'role': role, 'registry_commit': phase['registry_commit'],
                'profile_digest': phase['profile_digest'],
                'prompt_text': role['prompt_text'] + '\nTask data:\n' + canonical_json(inputs).decode()}
        job = {'id': identity(), 'phase_id': phase['id'], 'step': step,
               'slot': slot, 'input': inputs, **extra}
        ordinal = await tx.connection.fetchval('SELECT count(*)+1 FROM jobs WHERE phase_id=$1 '
                                              'AND step=$2', phase['id'], step)
        await tx.save('jobs', job, phase_id=phase['id'], step=step, scope='phase',
                      ordinal=ordinal, slot=slot, state='queued', creation_cursor=tx.cursor)
        return job

    async def query(self, principal, route, entity_id=None, cursor=0):
        if principal != 'local_operator':
            raise Problem('forbidden', 'Operator authorization required.')
        table = {'phases': 'phases', 'attempts': 'attempts', 'overview': 'phases', 'events': 'events'}.get(route)
        if table is None:
            raise Problem('not_found', 'Resource unavailable.')
        if entity_id:
            validate('Id', entity_id)
        result = await self.store.read(table, entity_id, cursor)
        if entity_id and not result['items'] and route != 'events':
            raise Problem('not_found', 'Resource unavailable.')
        return result

    async def wait(self, deadline, cursor=None):
        return await self.store.wait(deadline, cursor)

    async def runner_request(self, runner_id, route, data, generation, request_id):
        from cursus.transport import request
        result = await request(self, runner_id, route, data, generation, request_id)
        if route == 'jobs/next' and result is None:
            import time
            await self.wait(time.monotonic() + self.settings['limits']['long_poll_seconds'])
            result = await request(self, runner_id, route, data, generation, request_id)
        return result

    async def maintain(self, trigger):
        if trigger != 'boot':
            return
        async def close_admission(tx):
            rows = await tx.connection.fetch('SELECT payload FROM runners')
            from cursus.store import payload
            for row in rows:
                runner = payload(row)
                runner['reconciled'] = False
                await tx.save('runners', runner)
            return {'closed': True}
        return await self.store.transact('control', 'boot', identity(), {}, close_admission)

    async def completed(self, tx, attempt, final):
        from cursus.contracts import _object
        job = attempt['claim']['job']
        phase = await tx.get('phases', job['phase_id'])
        if not phase or phase['state'] in ('delivered', 'canceled'):
            raise Problem('state_conflict', 'Phase cannot advance.')
        _object(final, {'kind'}, {'value', 'reason', 'classification'})
        try:
            decision = self.decide(phase, {'kind': 'final', 'job': job, 'final': final,
                'attempt_id': attempt['id'], 'enrollment': self.enrolled(phase['input']['repo']),
                'repair_retries': self.settings['limits']['repair_retries'],
                'intent_id': identity(), 'lane_id': identity(), 'package_row_id': identity()})
        except (Problem, TypeError, KeyError, AttributeError) as exc:
            phase.update(state='parked', reason=exc.code if isinstance(exc, Problem) else 'invalid_result')
            decision = {'phase': phase}
        phase = decision['phase']
        phase['revision'] += 1
        attempt['status'] = 'unknown' if final['kind'] == 'unknown' else 'terminal'
        attempt['final'] = final
        await tx.connection.execute("UPDATE jobs SET state='done' WHERE id=$1", job['id'])
        if 'plan' in decision:
            await tx.revision('plans', phase['id'], 1, decision['plan'])
            package = decision['plan']['packages'][0]
            await tx.save('packages', {'id': phase['package_row_id'], 'package': package,
                          'state': 'ready'}, phase_id=phase['id'], plan_revision=1,
                          package_id=package['id'])
            await tx.save('integration_lanes', {'id': phase['lane_id'], 'target_sha': phase['base_sha'],
                          'state': 'active'}, phase_id=phase['id'], group_id='default')
        if job['step'] == 'resolve_input' and 'spec' in phase:
            await tx.revision('specs', phase['id'], 2, {'text': phase['spec'], 'base_sha': phase['base_sha']})
        if 'confirmed_intent' in decision:
            publication = await tx.get('publications', decision['confirmed_intent'])
            publication.update(state='confirmed', result=final['value'])
            await tx.save('publications', publication, state='confirmed')
        if 'intent' in decision:
            intent = decision['intent']
            await tx.save('publications', dict(intent, state='pending'), phase_id=phase['id'],
                          lane_id=phase['lane_id'], state='pending')
        await tx.save('phases', phase)
        if phase.get('package_row_id'):
            package = await tx.get('packages', phase['package_row_id'])
            package['state'] = phase['state']
            if 'candidate' in phase:
                package['accepted_candidate'] = phase['candidate']
            await tx.save('packages', package)
        if 'next' in decision:
            next_job = decision['next']
            await self.enqueue(tx, phase, next_job['step'], next_job['slot'], next_job['input'],
                               **{k: v for k, v in next_job.items() if k not in ('step','slot','input')})
        await tx.event(phase['id'], 'transition', {'state': phase['state'], 'step': job['step']})
