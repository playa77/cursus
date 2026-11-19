"""Closed M1 protocol shapes; semantic ownership checks stay in Control."""

from cursus.contracts import (_object, _text, _id, _integer, _enum, _hex,
                              _repo, _ref, _candidate, _time, _fail)


SLOTS = ('worker', 'verifier', 'frontier', 'repository')
STEPS = ('resolve_input', 'plan', 'scout', 'produce', 'verify', 'review',
         'stage_integration', 'advance_integration', 'inspect_target',
         'reconcile_publication', 'publish_pr')


def role(value):
    _object(value, {'name','tier','cli','model','reasoning','tools','timeout_seconds'}, {'provider','prompt','prompt_text'})
    for field in ('name','model','reasoning'):
        _text(value[field])
    _enum(value['tier'], ('organization','production'))
    _enum(value['cli'], ('pi','claude','codex','agy'))
    _integer(value['timeout_seconds'])
    if not isinstance(value['tools'], list) or any(not isinstance(t, str) or '*' in t for t in value['tools']):
        _fail()
    if value['tier'] == 'production' and value['cli'] != 'pi':
        _fail()
    if value['tier'] == 'organization' and set(value['tools']) - {'read','list','search'}:
        _fail()
    return value


def invocation(value):
    _object(value, {'role','registry_commit','profile_digest','prompt_text'})
    role(value['role'])
    _hex(value['registry_commit'], 40)
    _hex(value['profile_digest'], 64)
    _text(value['prompt_text'])
    return value


def criterion(value):
    _object(value, {'id','requirement','check'})
    _text(value['id'])
    _text(value['requirement'])
    check = value['check']
    kind = _enum(check.get('kind') if isinstance(check, dict) else None, ('command','review'))
    if kind == 'command':
        _object(check, {'kind','command_id','expected_exit'}, {'required_literal'})
        _text(check['command_id'])
        if type(check['expected_exit']) is not int or not 0 <= check['expected_exit'] <= 255:
            _fail()
        if 'required_literal' in check:
            _text(check['required_literal'])
    else:
        _object(check, {'kind','pass_rule','evidence'})
        _text(check['pass_rule'])
        if not isinstance(check['evidence'], list) or not check['evidence']:
            _fail()
    return value


def plan(value):
    _object(value, {'packages','phase_check_ids'}, {'delivery_groups'})
    packages = value['packages']
    if not isinstance(packages, list) or not 1 <= len(packages) <= 100:
        _fail('invalid_plan', 'Expected one to 100 packages.')
    ids = []
    for package in packages:
        _object(package, {'id','dependencies','objective','inputs','criteria'})
        name = _text(package['id'])
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            _fail()
        ids.append(name)
        _text(package['objective'])
        if not isinstance(package['dependencies'], list) or not isinstance(package['inputs'], list) or not isinstance(package['criteria'], list) or not package['criteria']:
            _fail()
        for item in package['criteria']:
            criterion(item)
        if len({c['id'] for c in package['criteria']}) != len(package['criteria']):
            _fail()
    if len(set(ids)) != len(ids):
        _fail('invalid_plan', 'Duplicate package ID.')
    edges = {p['id']: p['dependencies'] for p in packages}
    done = set()
    def visit(name, active):
        if name not in edges or name in active:
            _fail('invalid_plan', 'Unknown or cyclic dependency.')
        if name in done:
            return
        deps = edges[name]
        if any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            _fail()
        for dep in deps:
            visit(dep, active | {name})
        done.add(name)
    for name in ids:
        visit(name, set())
    groups = value.get('delivery_groups', [{'id':'default', 'package_ids':ids}])
    if not isinstance(groups, list) or not groups:
        _fail()
    members, group_ids = [], []
    for group in groups:
        _object(group, {'id','package_ids'})
        name = _text(group['id'])
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            _fail()
        group_ids.append(name)
        if not isinstance(group['package_ids'], list) or not group['package_ids']:
            _fail()
        members.extend(group['package_ids'])
        if any(d not in group['package_ids'] for p in packages if p['id'] in group['package_ids'] for d in p['dependencies']):
            _fail('invalid_plan', 'Delivery groups must be independent.')
    if len(set(group_ids)) != len(group_ids) or len(members) != len(ids) or set(members) != set(ids):
        _fail('invalid_plan', 'Groups must partition the plan.')
    if not isinstance(value['phase_check_ids'], list) or not value['phase_check_ids']:
        _fail()
    return value


def job(value):
    _object(value, {'id','phase_id','step','input','slot'}, {'package_id','group_id','invocation','publication_id'})
    _id(value['id'])
    _id(value['phase_id'])
    _enum(value['step'], STEPS)
    _enum(value['slot'], SLOTS)
    if not isinstance(value['input'], dict):
        _fail()
    if 'invocation' in value:
        invocation(value['invocation'])
    if 'publication_id' in value:
        _id(value['publication_id'])
    return value


def claim(value):
    _object(value, {'job','attempt_id','runner_id','request_id'})
    job(value['job'])
    for field in ('attempt_id','runner_id','request_id'):
        _id(value[field])
    return value


def final(value):
    kind = _enum(value.get('kind') if isinstance(value, dict) else None,
                 ('completed','failed','unknown','interrupted','canceled'))
    if kind == 'completed':
        _object(value, {'kind','value'})
    else:
        _object(value, {'kind','reason'}, {'classification'})
        _text(value['reason'])
    return value


def event(value):
    _object(value, {'attempt_id','seq','kind','payload'})
    _id(value['attempt_id'])
    _integer(value['seq'])
    kind = _enum(value['kind'], ('started','log','usage','final'))
    data = value['payload']
    if kind == 'final':
        final(data)
    elif kind == 'log':
        _object(data, {'stream','text'})
        _enum(data['stream'], ('stdout','stderr','system'))
        _text(data['text'], nonempty=False)
        if len(data['text'].encode()) > 65536:
            _fail('payload_too_large', 'Log exceeds byte limit.')
    elif kind == 'started':
        _object(data, {'service_activation','time'})
        _id(data['service_activation'])
        _time(data['time'])
    else:
        _object(data, set(), {'input_tokens','output_tokens','currency','cost'})
        for field in ('input_tokens','output_tokens'):
            if field in data:
                _integer(data[field], 0)
        if 'cost' in data:
            import decimal
            try:
                cost = decimal.Decimal(_text(data['cost']))
                if not cost.is_finite() or cost < 0 or not data.get('currency'):
                    _fail()
            except decimal.InvalidOperation:
                _fail()
    return value


def ack(value):
    _object(value, {'committed_through','disposition','next_expected'})
    _integer(value['committed_through'], 0)
    _integer(value['next_expected'])
    _enum(value['disposition'], ('active','terminal','stale'))
    if value['next_expected'] != value['committed_through'] + 1:
        _fail()
    return value


def reply(value):
    _object(value, {'entity_id','state','revision','cursor'})
    _id(value['entity_id'])
    _integer(value['revision'])
    _integer(value['cursor'], 0)
    _text(value['state'])
    return value


VALIDATORS = {'Role': role, 'Invocation': invocation, 'Criterion': criterion,
              'Plan': plan, 'Job': job, 'Claim': claim, 'Final': final, 'Event': event,
              'Ack': ack, 'Reply': reply}
