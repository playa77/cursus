"""Revision-bound guided intake and fixed-seat, three-round debate decisions."""
from copy import deepcopy
from uuid import uuid4
from cursus.contracts import Problem, _object, validate
from cursus.workflows import plan


def text(value):
    if not isinstance(value,str) or not value.strip() or len(value.encode()) > 262144:
        raise Problem('invalid_result','Expected bounded nonempty text.')
    return value


def questions(value):
    if not isinstance(value,list) or not 1 <= len(value) <= 50:
        raise Problem('invalid_result','Expected bounded questions.')
    result=[]
    for item in value:
        _object(item,{'text','required'})
        text(item['text'])
        if type(item['required']) is not bool:
            raise Problem('invalid_result','Required must be boolean.')
        result.append(dict(item,id=str(uuid4())))
    if not any(q['required'] for q in result):
        raise Problem('invalid_result','Question round needs a required input.')
    return result


def assignments(roles):
    names=('advocate','critic','judge')
    if any(n not in roles for n in names):
        raise Problem('invalid_config','Three debate roles are required.')
    if {roles[n]['cli'] for n in names} != {'claude','codex','agy'}:
        raise Problem('invalid_config','Debate seats require three distinct frontier CLIs.')
    if roles['advocate']['cli'] != roles['planner']['cli'] or roles['advocate']['cli'] != roles['interviewer']['cli']:
        raise Problem('invalid_config','Advocate must use the configured author CLI.')


def interview_job(phase):
    return {'step':'interview','slot':'frontier','role':'interviewer','input':{
        'transcript':phase.get('interviews',[]),'spec':phase.get('spec'),
        'questions':phase.get('questions',[]),'spec_revision':phase.get('spec_revision',1)}}


def planning_job(phase,enrollment):
    return {'step':'plan','slot':'frontier','role':'planner','input':{
        'workflow':phase['input']['workflow'],'spec':phase['spec'],'repo':phase['input']['repo'],
        'base_sha':phase['base_sha'],'checks':enrollment['checks'],
        'phase_check_ids':enrollment['phase_check_ids']}}


def start(phase,mode):
    phase['debate']={'mode':mode,'round':1,'document':phase['draft_plan'] if mode=='plan' else phase['spec'],
                     'prior_upheld':[]}
    return seat_job(phase,'rationale')


def seat_job(phase,seat):
    debate=phase['debate']
    fields={'rationale':[], 'critic':['rationale'], 'reply':['rationale','objections'],
            'judge':['rationale','objections','responses'],
            'revision':['rationale','objections','responses','judgment']}[seat]
    inputs={k:debate[k] for k in fields}
    inputs.update(mode=debate['mode'],round=debate['round'],seat=seat,document=debate['document'],
                  prior_upheld=debate['prior_upheld'])
    role={'rationale':'advocate','critic':'critic','reply':'advocate','judge':'judge','revision':'advocate'}[seat]
    return dict(step='debate',slot='frontier',role=role,input=inputs)


def finish(phase,change):
    from cursus.workflows import decide
    if phase['debate']['mode']=='spec':
        phase.update(spec=phase['debate']['document'],spec_approved=True,spec_revision=phase.get('spec_revision',2)+1)
        return {'phase':phase,'next':planning_job(phase,change['enrollment']), 'spec_revision':True}
    phase['plan_approved']=True
    value=phase['debate']['document']
    return decide(phase,dict(change,job=dict(change['job'],step='plan'),final={'kind':'completed','value':value}))


def next_round(phase,change):
    debate=phase['debate']
    if debate['round'] >= min(3,change.get('debate_rounds',3)):
        phase.update(state='parked',reason='Debate round cap reached with unresolved blockers.')
        return {'phase':phase}
    debate['round']+=1
    debate['prior_upheld']=[o for o in debate['objections'] if o['id'] in {r['id'] for r in debate['judgment']['rulings'] if r['upheld']}]
    for key in ('rationale','objections','responses','judgment'):
        debate.pop(key,None)
    return {'phase':phase,'next':seat_job(phase,'rationale')}


def decide(snapshot,change):
    phase=deepcopy(snapshot)
    job=change['job']
    final=change['final']
    if final['kind'] != 'completed':
        phase.update(state='parked',reason=final.get('classification',final.get('reason','Conversation failed.')))
        return {'phase':phase}
    value=final['value']
    step=job['step']
    if step=='resolve_input':
        _object(value,{'base_sha'}, {'text','source_commit'})
        validate('Sha',value['base_sha'],object_format=change['enrollment'].get('object_format','sha1'))
        phase.update(base_sha=value['base_sha'],state='planning')
        if phase['input']['source']['kind']=='interview':
            return {'phase':phase,'next':interview_job(phase)}
        if phase['input']['source']['kind']=='repo' and value.get('source_commit') != phase['input']['source']['commit']:
            raise Problem('invalid_result','Resolved source commit differs.')
        phase.update(spec=text(value['text']),spec_revision=2)
        return {'phase':phase,'next':start(phase,'spec'),'spec_revision':True}
    if step=='interview':
        if phase.get('questions') and any(q['required'] and 'answer' not in q for q in phase['questions']):
            raise Problem('state_conflict','Required questions are unanswered.')
        _object(value,{'kind'}, {'questions','text'})
        phase.setdefault('interviews',[]).append({'input':job['input'],'result':value,'attempt_id':change['attempt_id']})
        phase['interview_round']=phase.get('interview_round',0)+1
        if value['kind']=='questions':
            _object(value,{'kind','questions'})
            if phase['interview_round'] >= change.get('interview_rounds',20):
                phase.update(state='parked',reason='Interview round cap reached.')
            else:
                phase['questions']=questions(value['questions'])
                phase['state']='intake'
            return {'phase':phase}
        _object(value,{'kind','text'})
        if value['kind'] != 'complete':
            raise Problem('invalid_result','Unknown interview result.')
        phase.update(spec=text(value['text']),spec_revision=phase.get('spec_revision',1)+1,questions=[])
        if phase.get('debate',{}).get('waiting_questions'):
            phase['debate']['waiting_questions']=False
            phase['debate']['document']=phase['spec']
            result=next_round(phase,change)
        else:
            result={'phase':phase,'next':start(phase,'spec') if phase['input']['spec_debate'] else planning_job(phase,change['enrollment'])}
        result['spec_revision']=True
        return result
    if step=='plan':
        phase['draft_plan']=plan(value,change['enrollment'])
        if phase['input'].get('form') in ('one-shot','ticket') or phase['input']['workflow']=='debug':
            if len(value['packages']) != 1:
                raise Problem('invalid_plan','This input requires one package.')
        return {'phase':phase,'next':start(phase,'plan')}
    debate=phase['debate']
    seat=job['input']['seat']
    expected=seat_job(phase,seat)
    if job['input'] != expected['input'] or job['invocation']['role'] != phase['roles'][expected['role']]:
        raise Problem('invalid_result','Debate seat or revision differs.')
    phase.setdefault('debate_history',[]).append({'input':job['input'],'result':value,'attempt_id':change['attempt_id'],
                                               'role':expected['role']})
    if seat=='rationale':
        _object(value,{'rationale'})
        debate['rationale']=text(value['rationale'])
        next_seat='critic'
    elif seat=='critic':
        _object(value,{'objections'})
        objections=value['objections']
        if not isinstance(objections,list) or len(objections)>100:
            raise Problem('invalid_result','Invalid objection count.')
        ids=set()
        for item in objections:
            _object(item,{'id','severity','evidence','fix'})
            name=text(item['id'])
            if name in ids or item['severity'] not in ('blocker','major','minor'):
                raise Problem('invalid_result','Invalid objection identity or severity.')
            ids.add(name)
            text(item['evidence']); text(item['fix'])
        debate['objections']=objections
        next_seat='reply'
    elif seat=='reply':
        _object(value,{'responses'})
        responses=value['responses']
        validate_ids(responses,debate['objections'])
        for item in responses:
            _object(item,{'id','disposition','rationale'})
            if item['disposition'] not in ('concede','rebut','amend'):
                raise Problem('invalid_result','Invalid advocate disposition.')
            text(item['rationale'])
        debate['responses']=responses
        next_seat='judge'
    elif seat=='judge':
        _object(value,{'rulings','required_amendments','questions','verdict'})
        validate_ids(value['rulings'],debate['objections'])
        for item in value['rulings']:
            _object(item,{'id','upheld','rationale'})
            if type(item['upheld']) is not bool:
                raise Problem('invalid_result','Invalid ruling.')
            text(item['rationale'])
        if value['verdict'] not in ('accept','continue') or not isinstance(value['required_amendments'],list):
            raise Problem('invalid_result','Invalid judgment.')
        for amendment in value['required_amendments']:
            text(amendment)
        if not isinstance(value['questions'],list) or (debate['mode']=='plan' and value['questions']):
            raise Problem('invalid_result','Questions require spec debate intake.')
        debate['judgment']=value
        upheld={r['id'] for r in value['rulings'] if r['upheld']}
        debate['blocking']=any(o['id'] in upheld and o['severity'] in ('blocker','major') for o in debate['objections'])
        if value['questions']:
            phase['questions']=questions(value['questions'])
            phase['state']='intake'
            debate['waiting_questions']=True
            return {'phase':phase}
        if value['required_amendments']:
            next_seat='revision'
        elif not debate['blocking']:
            return finish(phase,change)
        else:
            return next_round(phase,change)
    else:
        if debate['mode']=='plan':
            debate['document']=plan(value,change['enrollment'])
        else:
            _object(value,{'kind','text'})
            if value['kind']!='complete':
                raise Problem('invalid_result','Revision must be a complete spec.')
            debate['document']=text(value['text'])
        if not debate['blocking']:
            return finish(phase,change)
        return next_round(phase,change)
    return {'phase':phase,'next':seat_job(phase,next_seat)}


def validate_ids(items,objections):
    if not isinstance(items,list) or len(items)!=len(objections) or any(not isinstance(i,dict) for i in items):
        raise Problem('invalid_result','Every objection needs one disposition.')
    ids=[i.get('id') for i in items]
    if any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or set(ids)!={o['id'] for o in objections}:
        raise Problem('invalid_result','Objection identities differ.')


async def answer(control,tx,value):
    phase=await tx.get('phases',value['phase_id'])
    if not phase or phase['state']!='intake':
        raise Problem('state_conflict','No current question round is awaiting input.')
    question=next((q for q in phase.get('questions',[]) if q['id']==value['question_id']),None)
    if not question or 'answer' in question:
        raise Problem('state_conflict','Question is absent or already answered.')
    question['answer']=value['text']
    phase.setdefault('interviews',[]).append({'question':deepcopy(question),'spec_revision':phase.get('spec_revision',1)})
    if all('answer' in q for q in phase['questions'] if q['required']):
        phase['state']='planning'
        job=interview_job(phase)
        await control.enqueue(tx,phase,job['step'],job['slot'],job['input'],role=job['role'])
    phase['revision']+=1
    await tx.event(phase['id'],'answered',value)
    await tx.save('phases',phase)
    return dict(entity_id=phase['id'],state=phase['state'],revision=phase['revision'],cursor=tx.cursor)
