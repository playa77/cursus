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
                     'references': []}
            await tx.save('phases', phase)
            await tx.revision('specs', phase_id, 1, source)
            await tx.event(phase_id, 'submitted', {'input': data})
            await self.enqueue(tx, phase, decision['step'], decision['slot'], decision['input'])
            return {'entity_id': phase_id, 'state': phase['state'], 'revision': 1, 'cursor': tx.cursor}
        return await self.store.transact(principal, 'operator/actions', request_id, value, transition)

    async def enqueue(self, tx, phase, step, slot, inputs, **extra):
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
        return await request(self, runner_id, route, data, generation, request_id)

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
        raise Problem('unsupported_milestone', 'Execution results are not enabled yet.')
