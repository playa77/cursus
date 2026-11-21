"""Sole coordination hub; no subprocess or external repository operations."""

from uuid import uuid4
from cursus.contracts import Problem, validate
from cursus import workflows


def identity():
    return str(uuid4())


class Control:
    def __init__(self, settings, store, decide=workflows.decide, artifacts=None):
        self.settings, self.store, self.decide = settings, store, decide
        self.artifacts = artifacts
        self.admin = None  # Settings/administration seam (cursus.admin.Admin); set by the composition root.

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
            if value['kind'] == 'set_drain':
                await tx.connection.execute('UPDATE coordination SET drain=$1', value['enabled'])
                await tx.event(None, 'drain', value)
                return dict(entity_id=self.settings['runner']['id'], state='drained' if value['enabled'] else 'open', revision=1, cursor=tx.cursor)
            if value['kind'] == 'answer':
                from cursus.conversations import answer
                return await answer(self,tx,value)
            if value['kind'] != 'submit':
                from cursus.recovery import action
                return await action(self, tx, value)
            unqualified = self.settings.get('unqualified_roles', [])
            if unqualified:
                # Loadable but incomplete: the website completes the roles (ADR 0018).
                raise Problem('roles_unqualified', 'Roles without a chosen model, reasoning or provider: '
                              + ', '.join(unqualified) + '. Complete them under Settings, Roles.')
            decision = self.decide({}, value)
            data = value['input']
            if data['plan_debate'] or data['spec_debate']:
                from cursus.conversations import assignments
                assignments(self.settings['roles'])
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
        role_name = extra.pop('role', None)
        if role_name:
            from cursus.contracts import canonical_json
            role = phase['roles'].get(role_name)
            if role is None:
                raise Problem('invalid_config', 'Required role is unavailable.')
            extra['invocation'] = {'role': role, 'registry_commit': phase['registry_commit'],
                'prompt_text': role['prompt_text'] + '\nTask data:\n' + canonical_json(inputs).decode()}
        if 'invocation' in extra:
            cli = extra['invocation']['role']['cli']
            slot = 'worker' if cli == 'pi' else cli
        job = {'id': identity(), 'phase_id': phase['id'], 'step': step,
               'slot': slot, 'input': inputs, **extra}
        await tx.event(phase['id'],'queued',{'job_id':job['id'],'step':step,'package_id':job.get('package_id')})
        ordinal = await tx.connection.fetchval('SELECT count(*)+1 FROM jobs WHERE phase_id=$1 '
                                              'AND step=$2', phase['id'], step)
        package_row = phase.get('package_rows',{}).get(job.get('package_id'),phase.get('package_row_id'))
        lane_row = phase.get('lanes',{}).get(job.get('group_id'),{}).get('row_id',phase.get('lane_id'))
        await tx.save('jobs', job, phase_id=phase['id'], package_id=package_row, lane_id=lane_row, step=step, scope='phase',
                      ordinal=ordinal, slot=slot, state='queued', creation_cursor=tx.cursor)
        return job

    async def query(self, principal, route, entity_id=None, cursor=0):
        if principal != 'local_operator':
            raise Problem('forbidden', 'Operator authorization required.')
        if route.startswith('browser/'):
            route = route.removeprefix('browser/')
            if route not in ('overview', 'phases', 'attempts'):
                raise Problem('not_found', 'Resource unavailable.')
            if entity_id:
                validate('Id', entity_id)
            return await self.store.browser_view(route, entity_id)
        if route == 'deployment':
            return await self.store.deployment()
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
        if trigger not in ('boot','tick'):
            return
        async def close_admission(tx):
            rows = await tx.connection.fetch('SELECT payload FROM runners')
            from cursus.store import payload
            for row in rows:
                runner = payload(row)
                if trigger=='boot':
                    runner['reconciled'] = False
                else:
                    from datetime import datetime,timezone
                    elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(runner['last_contact'])).total_seconds()
                    limit=self.settings['limits'].get('heartbeat_seconds',10)*self.settings['limits'].get('unreachable_after_missed_heartbeats',3)
                    runner['reachable']=elapsed < limit
                await tx.save('runners', runner)
            return {'closed': True}
        return await self.store.transact('control', trigger, identity(), {}, close_admission)

    async def completed(self, tx, attempt, final):
        from cursus.contracts import _object
        job = attempt['claim']['job']
        phase = await tx.get('phases', job['phase_id'])
        if not phase or phase['state'] in ('delivered', 'canceled'):
            raise Problem('state_conflict', 'Phase cannot advance.')
        _object(final, {'kind'}, {'value', 'reason', 'classification'})
        parent_id=job['input'].get('debug_attempt_id')
        if parent_id:
            parent=await tx.get('attempts',parent_id)
            if (not parent or parent['status'] not in ('active','unknown') or
                    phase.get('debug_checkpoint',{}).get('candidate') != job['input']['candidate']):
                attempt.update(status='terminal',final=final)
                await tx.connection.execute("UPDATE jobs SET state='done' WHERE id=$1",job['id'])
                await tx.event(phase['id'],'stale_verification',{'attempt_id':attempt['id']})
                return
        if phase['state'] == 'canceling':
            attempt.update(status='unknown' if final['kind'] == 'unknown' else 'terminal', final=final)
            await tx.save('attempts',attempt,status=attempt['status'])
            held = await tx.connection.fetchval("SELECT count(*) FROM attempts WHERE phase_id=$1 AND status IN ('active','unknown')",phase['id'])
            pending = await tx.connection.fetchval("SELECT count(*) FROM publications WHERE phase_id=$1 AND state='pending'",phase['id'])
            phase['state'] = 'canceling' if held or pending else 'canceled'
            await tx.save('phases',phase)
            await tx.connection.execute("UPDATE jobs SET state='done' WHERE id=$1",job['id'])
            return
        if job['step'] == 'verify' and final['kind'] == 'completed':
            from cursus.artifact_control import verify_ready
            await verify_ready(tx, attempt, final['value'])
        planning_value = final.get('value',{})
        if job['step']=='debate' and not (isinstance(planning_value,dict) and 'packages' in planning_value):
            planning_value = phase.get('debate',{}).get('document',{})
        if not isinstance(planning_value,dict):
            planning_value = {}
        try:
            decision = self.decide(phase, {'kind': 'final', 'job': job, 'final': final,
                'attempt_id': attempt['id'], 'enrollment': self.enrolled(phase['input']['repo']),
                'debate_rounds':self.settings['limits'].get('debate_rounds',3),
                'interview_rounds':self.settings['limits'].get('interview_rounds',20),
                'debug_turns':self.settings['limits'].get('debug_turns',10),
                'repair_retries': self.settings['limits']['repair_retries'],
                'intent_id': identity(), 'lane_id': identity(), 'package_row_id': identity(),
                'package_ids': {p['id']: identity() for p in planning_value.get('packages', []) if isinstance(p,dict) and 'id' in p},
                'lane_ids': {g['id']: identity() for g in planning_value.get('delivery_groups', [{'id':'default'}]) if isinstance(g,dict) and 'id' in g}})
        except (Problem, TypeError, KeyError, AttributeError) as exc:
            phase.update(state='parked', reason=exc.code if isinstance(exc, Problem) else 'invalid_result')
            decision = {'phase': phase}
        phase = decision['phase']
        phase['revision'] += 1
        attempt['status'] = 'unknown' if final['kind'] == 'unknown' and final.get('classification') != 'publication_unknown' else 'terminal'
        attempt['final'] = final
        await tx.connection.execute("UPDATE jobs SET state='done' WHERE id=$1", job['id'])
        if 'plan' in decision:
            await tx.revision('plans', phase['id'], 1, decision['plan'])
            for package in decision['plan']['packages']:
                row_id = phase.get('package_rows', {}).get(package['id'], phase.get('package_row_id'))
                await tx.save('packages', {'id': row_id, 'package': package, 'state':'ready'},
                              phase_id=phase['id'], plan_revision=1, package_id=package['id'])
            lanes = phase.get('lanes', {'default':{'row_id':phase.get('lane_id')}})
            for name, lane in lanes.items():
                await tx.save('integration_lanes', {'id':lane['row_id'], 'target_sha':phase['base_sha'],
                    'state':'active'}, phase_id=phase['id'], group_id=name)
        if (job['step'] == 'resolve_input' and 'spec' in phase) or decision.get('spec_revision'):
            phase['spec_revision'] = phase.get('spec_revision',2)
            await tx.revision('specs', phase['id'], phase['spec_revision'], {'text': phase['spec'], 'base_sha': phase['base_sha']})
        if 'confirmed_intent' in decision:
            publication = await tx.get('publications', decision['confirmed_intent'])
            publication.update(state='confirmed', result=final['value'])
            await tx.save('publications', publication, state='confirmed')
        if 'intent' in decision:
            intent = decision['intent']
            await tx.save('publications', dict(intent, state='pending'), phase_id=phase['id'],
                          lane_id=decision.get('lane_id', phase.get('lane_id')), state='pending')
        if 'command' in decision:
            from cursus.recovery import command
            item = dict(decision['command'])
            target = await tx.get('attempts',item.pop('attempt_id'))
            await command(tx,target,item.pop('action'),**item)
        await tx.save('phases', phase)
        for name, state in phase.get('schedule', {}).items():
            row = await tx.get('packages', phase['package_rows'][name])
            row.update(state)
            await tx.save('packages', row)
        if phase.get('package_row_id'):
            package = await tx.get('packages', phase['package_row_id'])
            package['state'] = phase['state']
            if 'candidate' in phase:
                package['accepted_candidate'] = phase['candidate']
            await tx.save('packages', package)
        for next_job in decision.get('jobs', []) + ([decision['next']] if 'next' in decision else []):
            await self.enqueue(tx, phase, next_job['step'], next_job['slot'], next_job['input'],
                               **{k: v for k, v in next_job.items() if k not in ('step','slot','input')})
        await tx.event(phase['id'], 'transition', {'state': phase['state'], 'step': job['step']})


    async def checkpoint(self, tx, attempt, value):
        from cursus.execution import report
        job = attempt['claim']['job']
        phase = await tx.get('phases',job['phase_id'])
        if job['step'] != 'debug' or phase['state'] in ('canceling','canceled','delivered','parked'):
            raise Problem('state_conflict','Checkpoint has no active debug owner.')
        candidate = validate('Candidate',value['candidate'],object_format=self.enrolled(phase['input']['repo']).get('object_format','sha1'))
        turn = value['turn']
        previous = phase.get('debug_checkpoint',{}).get('turn',0)
        ref = f"refs/heads/wp/{phase['id']}/{job['package_id']}/{attempt['id']}/checkpoints/{turn}"
        if (turn != previous+1 or turn > self.settings['limits'].get('debug_turns',10)
                or candidate['base_sha'] != job['input']['base_sha'] or candidate['repo'] != phase['input']['repo']
                or candidate['attempt_ref'] != ref):
            raise Problem('invalid_candidate','Debug checkpoint ownership or turn differs.')
        report(value['report'])
        phase.update(debug_checkpoint=value,debug_passed=False)
        await tx.save('phases',phase)
        await self.enqueue(tx,phase,'verify','verifier',{'candidate':candidate,
            'criteria':job['input']['package']['criteria'],'checks':self.enrolled(candidate['repo'])['checks'],
            'debug_attempt_id':attempt['id']},package_id=job['package_id'])
