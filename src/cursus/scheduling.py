"""Parallel package projections and serialized, independently published lanes.

Each package reuses the exact single-candidate gates. Only the lane owner may
stage or publish; other reviewed packages wait against the committed lane head.
"""
from copy import deepcopy
from cursus.contracts import Problem
from cursus.workflows import plan, single_decide


FIELDS = ('candidate','creator','report','evidence','review','staged','staged_patch',
          'candidate_patch','integration_evidence','integration_review','repair_count',
          'repair_findings','reason','intent','state','target_sha','drift_count')


def decide_phase(snapshot, change):
    phase = deepcopy(snapshot)
    job = change['job']
    if job['step']=='reconcile_publication' and change['final']['kind']=='completed' and change['final']['value'].get('kind')=='confirmed':
        job = dict(job,step=job['input']['intent']['kind'])
        change = dict(change,job=job,final={'kind':'completed','value':change['final']['value']['result']})
    decision = {'phase': phase, 'jobs': []}
    if job['step'] == 'plan':
        value = plan(change['final']['value'], change['enrollment'])
        phase['plan'] = value
        phase['schedule'] = {p['id']: {'state':'blocked'} for p in value['packages']}
        groups = value.get('delivery_groups', [{'id':'default', 'package_ids':list(phase['schedule'])}])
        phase['lanes'] = {g['id']: dict(g, head=phase['base_sha'], remote_head=None,
                                       owner=None, target_sha=phase['base_sha'], state='active', row_id=change['lane_ids'][g['id']]) for g in groups}
        phase['package_rows'] = change['package_ids']
        decision['plan'] = value
    else:
        name = job.get('package_id')
        if name not in phase['schedule']:
            raise Problem('invalid_result', 'Package result has no current plan owner.')
        state = phase['schedule'][name]
        group = next(g for g in phase['lanes'].values() if name in g['package_ids'])
        if job['step'] == 'advance_integration' and change['final']['kind'] == 'completed':
            intent = state['intent']
            if change['final']['value'] != {'ref':intent['head_ref'], 'sha':intent['head_sha']}:
                raise Problem('publication_mismatch', 'Lane confirmation differs.')
            group.update(head=intent['head_sha'], remote_head=intent['head_sha'], target_sha=intent['target_sha'],owner=None)
            state['state'] = 'integrated'
            decision['confirmed_intent'] = intent['id']
        else:
            projection = {k:v for k,v in phase.items() if k not in FIELDS}
            projection.update(state)
            package = next(p for p in phase['plan']['packages'] if p['id'] == name)
            projection.update(plan={'packages':[package], 'phase_check_ids':phase['plan']['phase_check_ids']},
                              base_sha=state['base_sha'], integration_head=group['head'],
                              remote_head=group['remote_head'])
            projection.setdefault('target_sha',group['target_sha'])
            if job['step']=='stage_integration':
                projection['integration_head']=job['input']['expected_head']
            # Target checks compare the enrolled target, not a dependent's base.
            if job['step'] == 'inspect_target':
                projection['base_sha'] = phase['base_sha']
            result = single_decide(projection, change)
            updated = result['phase']
            for key in FIELDS:
                if key in updated:
                    state[key] = updated[key]
            for key in ('intent','confirmed_intent'):
                if key in result:
                    decision[key] = result[key]
                    decision['lane_id'] = group['row_id']
            if 'next' in result:
                upcoming = result['next']
                upcoming.update(package_id=name, group_id=group['id'])
                if upcoming['step'] == 'stage_integration' and group['owner'] != name:
                    state['state'] = 'waiting_integration'
                else:
                    decision['jobs'].append(upcoming)
            if updated['state'] == 'delivered':
                group['state'] = 'delivered'
                phase['references'].extend(updated['references'])
    for group in phase['lanes'].values():
        for package in phase['plan']['packages']:
            name = package['id']
            if name not in group['package_ids']:
                continue
            state = phase['schedule'][name]
            if state['state'] == 'blocked' and all(phase['schedule'][d]['state'] == 'integrated' for d in package['dependencies']):
                state.update(state='execution', base_sha=group['head'])
                decision['jobs'].append({'step':'produce','slot':'worker','role':'worker',
                    'package_id':name,'group_id':group['id'], 'input':{'repo':phase['input']['repo'],
                    'base_sha':group['head'], 'spec':phase['spec'], 'package':package, 'findings':[]}})
            if state['state'] == 'waiting_integration' and group['owner'] is None:
                group['owner'] = name
                state['state'] = 'integration'
                decision['jobs'].append({'step':'stage_integration','slot':'repository',
                    'package_id':name,'group_id':group['id'], 'input':{'repo':phase['input']['repo'],
                    'expected_head':group['head'], 'candidate':state['candidate']}})
        if all(phase['schedule'][n]['state'] == 'integrated' for n in group['package_ids']) and group['state'] == 'active':
            # The last combined tree has already passed every phase check.
            name = group['package_ids'][-1]
            state = phase['schedule'][name]
            intent = dict(state['intent'], id=change['intent_id'], kind='publish_pr',
                          head_sha=group['head'], expected_old=group['head'],target_sha=group['target_sha'])
            state.update(intent=intent, state='delivery')
            group['state'] = 'delivery'
            decision.update(intent=intent, lane_id=group['row_id'])
            decision['jobs'].append({'step':'publish_pr','slot':'repository','package_id':name,
                'group_id':group['id'], 'publication_id':intent['id'],
                'input':{'repo':phase['input']['repo'], 'intent':intent}})
    if any(s['state'] == 'parked' for s in phase['schedule'].values()):
        phase.update(state='parked', reason='Package gate failed; inspect package schedule.')
    elif all(g['state'] == 'delivered' for g in phase['lanes'].values()):
        phase['state'] = 'delivered'
    else:
        phase['state'] = 'execution'
    return decision
