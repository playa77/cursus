"""Pure M1 state machine: exact evidence gates precede every publication intent."""

from copy import deepcopy
from hashlib import sha256
from cursus.contracts import Problem, canonical_json, validate, _object, _path
from cursus.execution import report, review


def admitted(value):
    if (value['workflow'] != 'code' or value['source']['kind'] == 'interview'
            or value['plan_debate'] or value['spec_debate']):
        raise Problem('unsupported_milestone', 'This workflow requires a later milestone.')


def plan(value, enrollment):
    _object(value, {'packages', 'phase_check_ids'})
    if not isinstance(value['packages'], list) or len(value['packages']) != 1:
        raise Problem('unsupported_milestone', 'M1 requires exactly one package.')
    package = value['packages'][0]
    _object(package, {'id', 'dependencies', 'objective', 'inputs', 'criteria'})
    if (not isinstance(package['id'], str) or not package['id'] or
            any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in package['id'])):
        raise Problem('invalid_plan', 'Invalid package identity.')
    if package['dependencies'] != [] or not isinstance(package['objective'], str) or not package['objective'].strip():
        raise Problem('invalid_plan', 'Invalid dependencies/objective.')
    if not isinstance(package['inputs'], list) or not isinstance(package['criteria'], list) or not package['criteria']:
        raise Problem('invalid_plan', 'Missing package inputs/criteria.')
    checks = {c['id'] for c in enrollment['checks']}
    if value['phase_check_ids'] != enrollment['phase_check_ids']:
        raise Problem('invalid_plan', 'Plan must retain every enrolled phase check.')
    seen = set()
    for item in package['criteria']:
        _object(item, {'id', 'requirement', 'check'})
        if not isinstance(item['id'], str) or not item['id'] or item['id'] in seen or not isinstance(item['requirement'], str):
            raise Problem('invalid_plan', 'Invalid/duplicate criterion.')
        seen.add(item['id'])
        check = item['check']
        if check.get('kind') == 'command':
            _object(check, {'kind', 'command_id', 'expected_exit'}, {'required_literal'})
            if check['command_id'] not in checks or type(check['expected_exit']) is not int or not 0 <= check['expected_exit'] <= 255:
                raise Problem('invalid_plan', 'Unknown command or invalid expected exit.')
            if 'required_literal' in check and not isinstance(check['required_literal'], str):
                raise Problem('invalid_plan', 'Invalid literal.')
        elif check.get('kind') == 'review':
            _object(check, {'kind', 'pass_rule', 'evidence'})
            if not isinstance(check['pass_rule'], str) or not check['pass_rule'].strip() or not isinstance(check['evidence'], list) or not check['evidence']:
                raise Problem('invalid_plan', 'Review needs observable pass rule and evidence.')
        else:
            raise Problem('unsupported_milestone', 'M1 code supports command/review criteria.')
    return value


def evidence(value, candidate, criteria, attempt_id):
    expected = [c for c in criteria if c['check']['kind'] == 'command']
    if not isinstance(value, list) or len(value) != len(expected):
        raise Problem('invalid_evidence', 'Missing required verifier evidence.')
    for criterion, item in zip(expected, value):
        _object(item, {'criterion_id', 'candidate', 'passed', 'observed_exit', 'output', 'verifier_attempt_id'})
        check = criterion['check']
        if (item['criterion_id'] != criterion['id'] or item['candidate'] != candidate
                or item['verifier_attempt_id'] != attempt_id or type(item['passed']) is not bool
                or type(item['observed_exit']) is not int or not isinstance(item['output'], str)):
            raise Problem('invalid_evidence', 'Evidence identity or observations differ.')
        passed = item['observed_exit'] == check['expected_exit'] and check.get('required_literal', '') in item['output']
        if passed != item['passed']:
            raise Problem('invalid_evidence', 'Evidence contradicts its observations.')
    return all(e['passed'] for e in value)


def decide(snapshot, change):
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
    if final['kind'] != 'completed':
        if final['kind'] not in ('failed', 'unknown', 'interrupted', 'canceled'):
            raise Problem('invalid_variant', 'Unknown final disposition.')
        phase.update(state='parked', reason=final.get('classification', final.get('reason', 'Execution unresolved.')))
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
        queue('produce', 'worker', {'repo': repo, 'base_sha': phase['base_sha'], 'spec': phase['spec'],
            'package': package, 'findings': phase.get('repair_findings', [])}, 'worker')
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
        queue('plan', 'frontier', {'workflow': 'code', 'spec': value['text'], 'repo': repo,
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
        package = phase['plan']['packages'][0]
        phase['lane_id'], phase['package_row_id'] = change['lane_id'], change['package_row_id']
        decision['plan'] = value
        produce()
    elif step == 'scout':
        _object(value, {'findings','source_references'})
        if not isinstance(value['findings'], list) or not isinstance(value['source_references'], list):
            raise Problem('invalid_result', 'Scout requires findings/source references.')
        queue('plan', 'frontier', {'workflow':'code', 'spec':phase['spec'], 'repo':repo,
            'base_sha':phase['base_sha'], 'checks':enrollment['checks'],
            'phase_check_ids':enrollment['phase_check_ids'], 'scout_findings':value}, 'planner')
    elif step == 'produce':
        _object(value, {'report', 'candidate'})
        report(value['report'])
        candidate = validate('Candidate', value['candidate'], object_format=enrollment.get('object_format', 'sha1'))
        ref = f"refs/heads/wp/{phase['id']}/{package['id']}/{attempt_id}/candidate"
        if candidate['kind'] != 'code' or candidate['repo'] != repo or candidate['base_sha'] != phase['base_sha'] or candidate['attempt_ref'] != ref:
            raise Problem('invalid_candidate', 'Candidate differs from production ownership.')
        phase.update(candidate=candidate, creator=attempt_id, report=value['report'], state='verification')
        queue('verify', 'verifier', {'candidate': candidate, 'criteria': criteria, 'checks': enrollment['checks']})
    elif step == 'verify':
        candidate = job['input']['candidate']
        if not evidence(value, candidate, job['input']['criteria'], attempt_id):
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
            queue('stage_integration', 'repository', {'repo': repo, 'expected_head': phase['base_sha'],
                                                     'candidate': phase['candidate']})
    elif step == 'stage_integration':
        _object(value, {'candidate', 'patch_identity', 'candidate_patch_identity'})
        staged = validate('Candidate', value['candidate'], object_format=enrollment.get('object_format', 'sha1'))
        if staged['repo'] != repo or staged['base_sha'] != phase['base_sha'] or staged['attempt_ref'] != f"refs/heads/cursus-stage/{phase['id']}/default/{attempt_id}":
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
        if value['base_sha'] != phase['base_sha']:
            phase.update(state='parked', reason='Target drift requires M2 revalidation.')
        else:
            intent = {'id': change['intent_id'], 'phase_id': phase['id'], 'repo': repo,
                      'head_ref': f"refs/heads/cursus/{phase['id']}/default", 'head_sha': phase['staged']['head_sha'],
                      'target_sha': phase['base_sha'], 'expected_old': None, 'kind': 'advance_integration'}
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
