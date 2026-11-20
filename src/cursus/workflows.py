"""Pure M1 state machine: exact evidence gates precede every publication intent."""

from copy import deepcopy
from hashlib import sha256
from cursus.contracts import Problem, canonical_json, validate, _object, _path
from cursus.execution import report, review


def admitted(value):
    if value['workflow'] not in ('code','debug'):
        raise Problem('unsupported_milestone', 'This workflow requires a later milestone.')


def plan(value, enrollment):
    validate('Plan', value)
    checks = {c['id'] for c in enrollment['checks']}
    if value['phase_check_ids'] != enrollment['phase_check_ids']:
        raise Problem('invalid_plan', 'Plan must retain every enrolled phase check.')
    for package in value['packages']:
        for criterion in package['criteria']:
            check = criterion['check']
            if check['kind'] == 'command' and check['command_id'] not in checks:
                raise Problem('invalid_plan', 'Unknown enrolled command.')
    return value


def evidence(value, candidate, criteria, attempt_id):
    expected = [c for c in criteria if c['check']['kind'] == 'command']
    if not isinstance(value, list) or len(value) != len(expected):
        raise Problem('invalid_evidence', 'Missing required verifier evidence.')
    for criterion, item in zip(expected, value):
        _object(item, {'criterion_id', 'candidate', 'passed', 'observed_exit', 'output', 'verifier_attempt_id'}, {'log'})
        check = criterion['check']
        if (item['criterion_id'] != criterion['id'] or item['candidate'] != candidate
                or item['verifier_attempt_id'] != attempt_id or type(item['passed']) is not bool
                or type(item['observed_exit']) is not int or not isinstance(item['output'], str)):
            raise Problem('invalid_evidence', 'Evidence identity or observations differ.')
        passed = item['observed_exit'] == check['expected_exit'] and check.get('required_literal', '') in item['output']
        if passed != item['passed']:
            raise Problem('invalid_evidence', 'Evidence contradicts its observations.')
    return all(e['passed'] for e in value)


def single_decide(snapshot, change):
    if change['kind'] == 'submit':
        value = change['input']
        admitted(value)
        return {'state': 'intake', 'step': 'resolve_input', 'slot': 'repository',
                'input': {'repo': value['repo'], 'source': value['source']}}
    if change['kind'] != 'final':
        raise Problem('unsupported_milestone', 'Action requires a later milestone.')
    phase = deepcopy(snapshot)
    job, final, attempt_id = change['job'], change['final'], change['attempt_id']
    _object(final, {'kind'}, {'value', 'classification', 'reason'})
    if job['step'] == 'reconcile_publication' and final['kind'] == 'completed':
        value = final['value']
        original = dict(job, step=job['input']['intent']['kind'])
        if value.get('kind') == 'no_effect':
            phase.update(state='delivery')
            phase.pop('reason',None)
            return {'phase':phase, 'next':{k:v for k,v in original.items() if k not in ('id','phase_id')}}
        return single_decide(phase, dict(change, job=original, final={'kind':'completed','value':value['result']}))
    if final['kind'] != 'completed':
        if final['kind'] not in ('failed', 'unknown', 'interrupted', 'canceled'):
            raise Problem('invalid_variant', 'Unknown final disposition.')
        phase.update(state='parked', reason=final.get('classification', final.get('reason', 'Execution unresolved.')))
        if final.get('classification') == 'publication_unknown' and job.get('publication_id'):
            return {'phase':phase, 'next':{'step':'reconcile_publication','slot':'repository',
                'publication_id':job['publication_id'], 'input':job['input'],
                **{k:job[k] for k in ('package_id','group_id') if k in job}}}
        return {'phase': phase}
    _object(final, {'kind', 'value'})
    value, step = final['value'], job['step']
    repo, enrollment = phase['input']['repo'], change['enrollment']
    phase.pop('reason', None)
    package = phase.get('plan', {}).get('packages', [{}])[0]
    criteria = package.get('criteria', [])
    decision = {'phase': phase}
    def queue(step, slot, inputs, role=None):
        decision['next'] = {'step': step, 'slot': slot, 'input': inputs}
        if role:
            decision['next']['role'] = role
        if package.get('id'):
            decision['next']['package_id'] = package['id']
    def produce():
        if phase['input']['workflow']=='debug':
            for key in ('debug_checkpoint','debug_passed','debug_evidence','debug_reproduced'):
                phase.pop(key,None)
        queue('debug' if phase['input']['workflow']=='debug' else 'produce', 'worker', {'repo': repo, 'base_sha': phase['base_sha'], 'spec': phase['spec'],
            'package': package, 'findings': phase.get('repair_findings', [])}, 'debug' if phase['input']['workflow']=='debug' else 'worker')
        phase['state'] = 'execution'
    def repair(reason):
        count = phase.get('repair_count', 0)
        if count >= change['repair_retries']:
            phase.update(state='parked', reason='Repair budget exhausted.')
        else:
            phase['repair_count'] = count + 1
            phase['repair_findings'] = reason
            produce()
    if step == 'resolve_input':
        _object(value, {'base_sha', 'text'}, {'source_commit'})
        validate('Sha', value['base_sha'], object_format=enrollment.get('object_format', 'sha1'))
        if not isinstance(value['text'], str) or not value['text'].strip() or len(value['text'].encode()) > 262144:
            raise Problem('invalid_result', 'Invalid resolved specification.')
        source = phase['input']['source']
        if source['kind'] == 'repo' and value.get('source_commit') != source['commit']:
            raise Problem('invalid_result', 'Resolved source commit differs.')
        phase.update(base_sha=value['base_sha'], spec=value['text'], state='planning')
        queue('plan', 'frontier', {'workflow': phase['input']['workflow'], 'spec': value['text'], 'repo': repo,
                                 'base_sha': value['base_sha'], 'checks': enrollment['checks'],
                                 'phase_check_ids': enrollment['phase_check_ids']}, 'planner')
    elif step == 'plan':
        if isinstance(value, dict) and value.get('kind') == 'scout_request':
            _object(value, {'kind','question','input_refs'})
            if phase.get('scout_requested') or not isinstance(value['question'], str) or not value['question'].strip() or value['input_refs'] != ['repository_snapshot']:
                raise Problem('invalid_plan', 'Scout request exceeds prepared inputs or one-scout limit.')
            phase['scout_requested'] = True
            queue('scout', 'worker', {'repo': repo, 'base_sha': phase['base_sha'], 'question': value['question'],
                                    'input_refs': value['input_refs']}, 'scout')
            return decision
        phase['plan'] = plan(value, enrollment)
        if phase['input'].get('form') in ('one-shot','ticket') or phase['input']['workflow']=='debug':
            if len(value['packages']) != 1:
                raise Problem('invalid_plan','This input requires exactly one package.')
        package = phase['plan']['packages'][0]
        phase['lane_id'], phase['package_row_id'] = change['lane_id'], change['package_row_id']
        decision['plan'] = value
        produce()
    elif step == 'scout':
        _object(value, {'findings','source_references'})
        if not isinstance(value['findings'], list) or not isinstance(value['source_references'], list):
            raise Problem('invalid_result', 'Scout requires findings/source references.')
        queue('plan', 'frontier', {'workflow':phase['input']['workflow'], 'spec':phase['spec'], 'repo':repo,
            'base_sha':phase['base_sha'], 'checks':enrollment['checks'],
            'phase_check_ids':enrollment['phase_check_ids'], 'scout_findings':value}, 'planner')
    elif step in ('produce','debug'):
        _object(value, {'report', 'candidate'})
        report(value['report'])
        candidate = validate('Candidate', value['candidate'], object_format=enrollment.get('object_format', 'sha1'))
        ref = f"refs/heads/wp/{phase['id']}/{package['id']}/{attempt_id}/candidate"
        if step == 'debug':
            if candidate != phase.get('debug_checkpoint',{}).get('candidate') or not phase.get('debug_passed') or value['report'] != phase['debug_checkpoint']['report']:
                raise Problem('invalid_candidate','Debug final must equal the exact passing checkpoint/report.')
            ref = candidate['attempt_ref']
        if candidate['kind'] != 'code' or candidate['repo'] != repo or candidate['base_sha'] != phase['base_sha'] or candidate['attempt_ref'] != ref:
            raise Problem('invalid_candidate', 'Candidate differs from production ownership.')
        phase.update(candidate=candidate, creator=attempt_id, report=value['report'], state='verification')
        if step == 'debug':
            phase['evidence'] = phase['debug_evidence']
            queue('review','frontier',{'candidate':candidate,'criteria':criteria,'evidence':phase['debug_evidence'],'creator':attempt_id},'reviewer')
        else:
            queue('verify', 'verifier', {'candidate': candidate, 'criteria': criteria, 'checks': enrollment['checks']})
    elif step == 'verify':
        candidate = job['input']['candidate']
        if job['input'].get('debug_attempt_id'):
            passed = evidence(value,candidate,job['input']['criteria'],attempt_id)
            phase.update(debug_passed=passed,debug_evidence=value)
            if not passed:
                phase['debug_reproduced']=True
            if passed and not phase.get('debug_reproduced'):
                phase.update(state='parked',reason='Debug requires executed reproduction evidence before accepting a fix.')
                action='stop'
            elif not passed and phase['debug_checkpoint']['turn'] >= change.get('debug_turns',10):
                phase.update(state='parked',reason='Debug turn budget exhausted.')
                action = 'stop'
            else:
                action = 'finish_debug' if passed else 'continue_debug'
            decision['command'] = {'attempt_id':job['input']['debug_attempt_id'],'action':action,
                                   'checkpoint':phase['debug_checkpoint'], 'evidence':value}
        elif not evidence(value, candidate, job['input']['criteria'], attempt_id):
            repair(value)
        elif job['input'].get('integration'):
            phase['integration_evidence'] = value
            if phase['staged_patch'] != phase['candidate_patch']:
                queue('review', 'frontier', {'candidate': candidate, 'criteria': criteria, 'evidence': value,
                      'creator': phase['creator'], 'integration': True}, 'reviewer')
            else:
                queue('inspect_target', 'repository', {'repo': repo})
        else:
            phase.update(evidence=value, state='review')
            queue('review', 'frontier', {'candidate': candidate, 'criteria': criteria, 'evidence': value,
                                       'creator': phase['creator']}, 'reviewer')
    elif step == 'review':
        if attempt_id == phase['creator']:
            raise Problem('invalid_review', 'Creator cannot review its own candidate.')
        review(value, criteria)
        if value['verdict'] != 'accept':
            repair(value['findings'] + value['required_repairs'])
        elif job['input'].get('integration'):
            phase['integration_review'] = value
            queue('inspect_target', 'repository', {'repo': repo})
        else:
            phase.update(review=value, state='integration')
            queue('stage_integration', 'repository', {'repo': repo, 'expected_head': phase.get('integration_head', phase['base_sha']),
                                                     'candidate': phase['candidate']})
    elif step == 'stage_integration':
        _object(value, {'candidate', 'patch_identity', 'candidate_patch_identity'})
        staged = validate('Candidate', value['candidate'], object_format=enrollment.get('object_format', 'sha1'))
        if staged['repo'] != repo or staged['base_sha'] != phase.get('integration_head', phase['base_sha']) or staged['attempt_ref'] != f"refs/heads/cursus-stage/{phase['id']}/{job.get('group_id', 'default')}/{attempt_id}":
            raise Problem('invalid_candidate', 'Staged identity differs.')
        validate('Digest', value['patch_identity'])
        validate('Digest', value['candidate_patch_identity'])
        phase.update(staged=staged, staged_patch=value['patch_identity'], candidate_patch=value['candidate_patch_identity'])
        phase_criteria = [{'id': 'phase:' + name, 'requirement': 'Enrolled phase check',
                          'check': {'kind': 'command', 'command_id': name, 'expected_exit': 0}}
                          for name in enrollment['phase_check_ids']]
        combined = criteria + [c for c in phase_criteria if c['id'] not in {i['id'] for i in criteria}]
        queue('verify', 'verifier', {'candidate': staged, 'criteria': combined,
                                    'checks': enrollment['checks'], 'integration': True})
    elif step == 'inspect_target':
        _object(value, {'base_sha'})
        if value['base_sha'] != phase.get('target_sha',phase['base_sha']):
            count=phase.get('drift_count',0)
            if count >= change['repair_retries']:
                phase.update(state='parked',reason='Target drift revalidation budget exhausted.')
            else:
                phase.update(drift_count=count+1,target_sha=value['base_sha'],
                             integration_head=phase['staged']['head_sha'],state='integration')
                queue('stage_integration','repository',{'repo':repo,'expected_head':phase['staged']['head_sha'],
                    'candidate':phase['staged'],'drift_target':value['base_sha']})
        else:
            intent = {'id': change['intent_id'], 'phase_id': phase['id'], 'repo': repo,
                      'head_ref': f"refs/heads/cursus/{phase['id']}/{job.get('group_id', 'default')}", 'head_sha': phase['staged']['head_sha'],
                      'target_sha': phase.get('target_sha',phase['base_sha']), 'expected_old': phase.get('remote_head'), 'kind': 'advance_integration'}
            phase.update(intent=intent, state='delivery')
            decision['intent'] = intent
            queue('advance_integration', 'repository', {'repo': repo, 'intent': intent})
            decision['next']['publication_id'] = intent['id']
    elif step == 'advance_integration':
        _object(value, {'ref', 'sha'})
        intent = phase['intent']
        if value != {'ref': intent['head_ref'], 'sha': intent['head_sha']}:
            raise Problem('publication_mismatch', 'Integration confirmation differs from intent.')
        decision['confirmed_intent'] = intent['id']
        intent = dict(intent, id=change['intent_id'], kind='publish_pr', expected_old=value['sha'])
        phase['intent'] = intent
        decision['intent'] = intent
        queue('publish_pr', 'repository', {'repo': repo, 'intent': intent})
        decision['next']['publication_id'] = intent['id']
    elif step == 'publish_pr':
        _object(value, {'repo', 'head_ref', 'head_sha', 'number', 'url'})
        intent = phase['intent']
        if (value['repo'] != repo or value['head_ref'] != intent['head_ref'] or value['head_sha'] != intent['head_sha']
                or type(value['number']) is not int or value['number'] <= 0
                or value['url'] != f"https://github.com/{repo['owner']}/{repo['name']}/pull/{value['number']}"):
            raise Problem('publication_mismatch', 'PR confirmation differs from verified head.')
        decision['confirmed_intent'] = intent['id']
        phase.update(state='delivered', references=[value])
    else:
        raise Problem('unsupported_milestone', 'Step is unavailable in M1.')
    return decision


def decide(snapshot, change):
    """Dispatch phase scheduling without sharing mutable package projections."""
    job = change.get('job', {})
    completed = change.get('final', {}).get('kind') == 'completed'
    inputs = snapshot.get('input', {})
    conversation = job.get('step') in ('interview','debate')
    conversation |= job.get('step') == 'resolve_input' and (inputs.get('source',{}).get('kind')=='interview' or inputs.get('spec_debate',False))
    value = change.get('final',{}).get('value',{})
    conversation |= (job.get('step') == 'plan' and completed and inputs.get('plan_debate',False)
                     and not snapshot.get('plan_approved') and isinstance(value,dict) and value.get('kind') != 'scout_request')
    if conversation:
        from cursus.conversations import decide as converse
        return converse(snapshot,change)
    if snapshot.get('schedule') or (snapshot.get('input',{}).get('form') == 'phase' and change.get('job', {}).get('step') == 'plan'
            and change.get('final', {}).get('kind') == 'completed'
            and isinstance(change['final'].get('value'), dict)
            and (len(change['final']['value'].get('packages', [])) > 1 or 'delivery_groups' in change['final']['value'])):
        from cursus.scheduling import decide_phase
        return decide_phase(snapshot, change)
    return single_decide(snapshot, change)
