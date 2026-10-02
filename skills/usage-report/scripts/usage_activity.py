"""Strict activity contract and semantics mirrored from muring-kb ai_work_records.

Uses the checked-in canonical schema subset without an external runtime dependency.
Synthetic canonical fixtures verify parity; no public projection is emitted here.
"""
from copy import deepcopy
from datetime import datetime, date, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'references/ai-task-activity.schema.json').read_text())


def check_schema_document(schema):
    supported={'$schema','title','type','properties','required','additionalProperties','anyOf','const','enum','items','minItems','maxItems','minLength','maxLength','pattern','format'}
    if set(schema)-supported:raise ValueError('Activity schema has unsupported keywords')
    if schema.get('type') not in (None,'object','array','string','number','null'):raise ValueError('Unsupported activity schema type')
    if schema.get('format') not in (None,'date','date-time','uri'):raise ValueError('Unsupported activity schema format')
    for child in schema.get('properties',{}).values():check_schema_document(child)
    for child in schema.get('anyOf',[]):check_schema_document(child)
    if 'items' in schema:check_schema_document(schema['items'])

check_schema_document(SCHEMA)


def check_schema(value, schema, path='activity'):
    def fail():raise ValueError(f'{path}: invalid activity contract value')
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:check_schema(value,choice,path);return
            except ValueError:pass
        fail()
    if 'const' in schema and (isinstance(value,bool)!=isinstance(schema['const'],bool) or value!=schema['const']):fail()
    if 'enum' in schema and not any(type(value)==type(v) and value==v for v in schema['enum']):fail()
    kind=schema.get('type')
    if kind=='null':
        if value is not None:fail()
    elif kind=='object':
        if not isinstance(value,dict) or not set(schema['required'])<=set(value):fail()
        if schema.get('additionalProperties') is False and set(value)-set(schema['properties']):fail()
        for key,item in value.items():check_schema(item,schema['properties'][key],path+'/'+key)
    elif kind=='array':
        if not isinstance(value,list) or not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100):fail()
        for index,item in enumerate(value):check_schema(item,schema['items'],path+'/'+str(index))
    elif kind=='number':
        if type(value) not in (int,float) or (isinstance(value,float) and not math.isfinite(value)):fail()
    elif kind=='string':
        if not isinstance(value,str) or not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',2000):fail()
        if len(value.encode('utf-16-le'))//2>schema.get('maxLength',2000):fail()
        if 'pattern' in schema and not re.search(schema['pattern'],value):fail()
        fmt=schema.get('format')
        try:
            if fmt=='date':
                if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):fail()
                date.fromisoformat(value)
            elif fmt=='date-time':
                if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])',value):fail()
                datetime.fromisoformat(value.replace('Z','+00:00'))
            elif fmt=='uri':
                if not urlsplit(value).scheme or any(c.isspace() for c in value):fail()
        except (ValueError,OverflowError):fail()


PUBLIC_KEYS = {'slug', 'title', 'problem', 'aiUse', 'result', 'verification', 'limitations', 'sourceUrl'}
PRIVATE_PATTERN = re.compile(
    r'(?:/(?:home|Users|mnt|tmp|var|etc|root)/|(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\|~/|'
    r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|'
    r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|'
    r'\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+)|'
    r'(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+)', re.I)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('A timestamp must include its UTC offset')
    return parsed.astimezone(timezone.utc)


def validate_public(projection):
    # Human review is still mandatory: pattern checks are not a privacy guarantee.
    if set(projection) != PUBLIC_KEYS:
        raise ValueError('Unexpected public projection fields')
    if PRIVATE_PATTERN.search(canonical(projection)):
        raise ValueError('Potential private path, identifier or credential in public projection')
    url = projection['sourceUrl']
    if url is not None:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Public source must be a credential-free HTTPS URL without query or fragment')
        if host in ('localhost', 'localhost.localdomain') or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
            raise ValueError('Private source host')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError('Private source address')


def validate_activity(activity):
    check_schema(activity, SCHEMA)
    # Reject nonfinite values, including the permissive Python JSON decoder's NaN.
    canonical(activity)
    evidence = {item['id']: item for item in activity['evidence']}
    if len(evidence) != len(activity['evidence']):
        raise ValueError('Duplicate evidence id')

    def walk(value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Blank activity strings must be null or omitted list items')
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('evidenceRefs', 'evidenceRef'):
                    refs = item if isinstance(item, list) else [item]
                    if len(refs) != len(set(refs)) or any(ref not in evidence for ref in refs):
                        raise ValueError('Duplicate or unresolved evidence reference')
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(activity)
    if any(activity[k] for k in ('actions', 'aiRole', 'humanRole', 'outcomes', 'knowledge')) and not evidence:
        raise ValueError('Reported work/roles/knowledge require explicit evidence')
    for outcome in activity['outcomes'] or []:
        if not outcome['evidenceRefs']:
            raise ValueError('An outcome needs evidence')
    for check in (activity['verification'] or {}).get('checks', []):
        if check['result'] in ('pass', 'fail') and not check['evidenceRefs']:
            raise ValueError('An executed check needs evidence')
    timing = activity['timing']
    precision = timing['precision']
    if precision == 'unknown':
        if timing['basis'] != 'unknown' or any(timing[k] is not None for k in ('startedAt', 'endedAt', 'occurredAt', 'occurredOn')):
            raise ValueError('Unknown timing cannot carry inferred dates')
    else:
        if timing['basis'] == 'unknown' or not timing['evidenceRefs']:
            raise ValueError('Known timing requires explicit source evidence')
        if precision == 'date':
            if timing['occurredOn'] is None or any(timing[k] is not None for k in ('startedAt', 'endedAt', 'occurredAt')):
                raise ValueError('Date precision needs only occurredOn, never fabricated midnight')
        elif timing['occurredAt'] is None or timing['occurredOn'] is not None:
            raise ValueError('Timestamp precision needs occurredAt, not occurredOn')
    if timing['basis'] == 'user_confirmed' and not any(evidence[r]['kind'] == 'user_statement' for r in timing['evidenceRefs']):
        raise ValueError('User-confirmed timing requires a user statement')
    if timing['startedAt'] and timing['endedAt'] and parse_time(timing['startedAt']) > parse_time(timing['endedAt']):
        raise ValueError('Task ends before it starts')
    for effect in activity['effects'] or []:
        before, after = effect['before'], effect['after']
        if (before is None) != (after is None):
            raise ValueError('Effect before/after must both be known or both null')
        if effect['kind'] == 'measured' and before is None:
            raise ValueError('Measured effect needs before and after values')
        if effect['kind'] == 'user_confirmed' and not any(evidence[r]['kind'] == 'user_statement' for r in effect['evidenceRefs']):
            raise ValueError('Confirmed effect requires user-statement evidence')
        if any(isinstance(v, float) and not math.isfinite(v) for v in (before, after)):
            raise ValueError('Nonfinite effect value')
    public = activity['publicCase']
    if public is not None:
        if public['projection'] is not None:
            validate_public(public['projection'])
        review = public['review']
        if review is not None and evidence[review['evidenceRef']]['kind'] != 'user_statement':
            raise ValueError('Public review must refer to an explicit user statement')
        if public['status'] == 'approved' and (review is None or public['projection'] is None or not public['evidenceRefs']):
            raise ValueError('Approved public case needs projection, review and evidence')
    validate_handoffs(activity)
    validate_decisions(activity)
    return activity



def validate_decisions(activity):
    ids = set(); documents = set()
    legacy = {x['document']: x['usage'] for x in activity['knowledge'] or []}
    for decision in activity.get('knowledgeDecisions') or []:
        path = Path(decision['document'])
        if not path.parts or ':' in decision['document'] or path.is_absolute() or '..' in path.parts or '\\' in decision['document'] or path.as_posix() != decision['document']:
            raise ValueError('Decision document must be a normalized KB-relative path')
        if decision['id'] in ids or decision['document'] in documents:
            raise ValueError('Duplicate knowledge decision id or document')
        ids.add(decision['id']); documents.add(decision['document'])
        if (decision['selection'] == 'search') != bool(decision['searchRefs']):
            raise ValueError('Search selection needs searchRefs; direct selection must not invent searches')
        if len(set(decision['searchRefs'])) != len(decision['searchRefs']):
            raise ValueError('Duplicate search reference')
        state = decision['decision']
        if state != 'unknown' and not decision['evidenceRefs']:
            raise ValueError('Known knowledge decision needs evidence')
        if state == 'applied':
            check = decision['verification']
            if not decision['plannedUse'] or check is None or check['result'] not in ('pass', 'fail') or not check['evidenceRefs']:
                raise ValueError('Applied knowledge needs actual use and verified outcome evidence')
        if state != 'unknown' and decision['document'] in legacy:
            if (legacy[decision['document']] == 'applied') != (state == 'applied'):
                raise ValueError('Legacy knowledge and decision contradict each other')


def validate_handoffs(activity):
    evidence = {e['id']: e for e in activity['evidence']}
    seen = set()
    for handoff in activity.get('handoffs') or []:
        if handoff['id'] in seen:
            raise ValueError('Duplicate handoff id')
        seen.add(handoff['id']); events = set()
        for event in handoff['events']:
            if event['id'] in events:
                raise ValueError('Duplicate handoff event id')
            events.add(event['id'])
            precision = event['precision']
            if precision == 'timestamp' and (event['at'] is None or event['occurredOn'] is not None):
                raise ValueError('Handoff timestamp needs only at')
            if precision == 'date' and (event['occurredOn'] is None or event['at'] is not None):
                raise ValueError('Handoff date must not invent midnight')
            if precision == 'unknown' and (event['at'] is not None or event['occurredOn'] is not None):
                raise ValueError('Unknown handoff time must remain null')
            kind, reporter = event['kind'], event['reportedBy']
            if reporter == 'user' and not any(evidence[r]['kind'] == 'user_statement' for r in event['evidenceRefs']):
                raise ValueError('User-reported handoff event needs user-statement evidence')
            if kind == 'cancelled' and reporter == 'transport':
                raise ValueError('Transport acceptance cannot establish task cancellation')
            if kind in ('received', 'started', 'blocked', 'completed', 'failed') and reporter not in ('recipient', 'user'):
                raise ValueError('Recipient state needs recipient or user evidence')
            if kind == 'dispatch_accepted' and reporter != 'transport':
                raise ValueError('Dispatch acceptance needs transport evidence')
            if kind == 'requested' and reporter not in ('sender', 'user'):
                raise ValueError('Request needs sender or user evidence')
            if (kind in ('completed', 'failed')) != (event['result'] is not None):
                raise ValueError('Completed/failed handoff requires a result; other events keep it null')


def validate(value, project=None, task_id=None):
    result = deepcopy(validate_activity(value))
    if project is not None:
        for handoff in result.get('handoffs') or []:
            if not any(e['project'] == project and e['taskId'] in (None, task_id) for e in (handoff['from'], handoff['to'])):
                raise ValueError('Handoff does not belong to this task endpoint')
    return result


def handoff_event(event, evidence):
    normalized = {k: deepcopy(v) for k, v in event.items() if k != 'evidenceRefs'}
    normalized['evidence'] = sorted(
        [{k: v for k, v in evidence[r].items() if k != 'id'} for r in event['evidenceRefs']], key=canonical)
    return normalized


def validate_collection(tasks):
    """Hold conflicting cross-task handoffs; KB owns timeline aggregation."""
    groups = {}
    for task in tasks:
        if 'activity' not in task:continue
        value = validate(task['activity'], task['project'], task['id'])
        evidence = {e['id']: e for e in value['evidence']}
        for handoff in value.get('handoffs') or []:
            header = canonical({k: handoff[k] for k in ('from', 'to', 'request')})
            group = groups.setdefault(handoff['id'], dict(header=header, events={}, terminal=set()))
            if task.get('conflict') or group['header'] != header:
                raise ValueError('handoff header/source conflict; synchronization held')
            for event in handoff['events']:
                normalized = canonical(handoff_event(event, evidence))
                if group['events'].setdefault(event['id'], normalized) != normalized:
                    raise ValueError('handoff event conflict; synchronization held')
                if event['kind'] in ('completed', 'failed', 'cancelled'):group['terminal'].add(event['id'])
            if len(group['terminal']) > 1:
                raise ValueError('handoff outcome conflict; synchronization held')


def merge_supplements(tasks, conflicts, records, digest):
    for name,data in records:
        if not isinstance(data,dict) or set(data)!={'version','project','id','activity'} or type(data['version']) is not int or data['version']!=1 or not all(isinstance(data[k],str) and data[k].strip() for k in ('project','id')):
            raise ValueError(f'activity supplement invalid wrapper: {name}')
        key=digest([data['project'],data['id']])
        if name!=key+'.json':raise ValueError(f'activity supplement filename mismatch: {name}')
        if key not in tasks:raise ValueError(f'activity supplement target missing: {name}')
        task=tasks[key]
        if key in conflicts or task.get('conflict') is True:raise ValueError(f'activity supplement target conflict: {name}')
        value=validate(data['activity'],data['project'],data['id'])
        if 'activity' in task and task['activity']!=value:raise ValueError(f'activity native/supplement conflict: {name}')
        task['activity']=value


def merge(tasks, conflicts, directory, read, digest):
    for key,task in tasks.items():
        if 'activity' in task:
            task['activity']=validate(task['activity'],task['project'],task['id'])
            if key in conflicts or task.get('conflict') is True:raise ValueError('activity task conflict')
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):raise ValueError('activity supplement directory invalid')
    records=[]
    for path in sorted(directory.glob('*')):
        if not path.is_file() or path.is_symlink() or not re.fullmatch(r'[0-9a-f]{64}\.json',path.name):raise ValueError('invalid activity supplement path')
        records.append((path.name,read(path)))
    merge_supplements(tasks,conflicts,records,digest)
    validate_collection(tasks.values())


def validate_transition(previous, current):
    """A previously recorded review state cannot change without new review evidence."""
    if current is not None:validate(current)
    current_handoffs = {h['id']: h for h in (current or {}).get('handoffs') or []}
    old_evidence = {e['id']: e for e in (previous or {}).get('evidence', [])}
    new_evidence = {e['id']: e for e in (current or {}).get('evidence', [])}
    decisions = {d['document']: d for d in (current or {}).get('knowledgeDecisions') or []}
    for old in (previous or {}).get('knowledgeDecisions') or []:
        new = decisions.get(old['document'])
        if new != old:
            raise ValueError('Existing knowledge decision conflicts; reconcile explicitly before replacement')
        refs = old['evidenceRefs'] + (old['verification'] or {}).get('evidenceRefs', [])
        if any(old_evidence[r] != new_evidence.get(r) for r in refs):
            raise ValueError('Existing knowledge decision evidence must be preserved')
    for old_handoff in (previous or {}).get('handoffs') or []:
        new_handoff = current_handoffs.get(old_handoff['id'])
        if new_handoff is None or any(old_handoff[k] != new_handoff[k] for k in ('from', 'to', 'request')):
            raise ValueError('Existing handoff headers must be preserved')
        events = {e['id']: e for e in new_handoff['events']}
        for old_event in old_handoff['events']:
            new_event = events.get(old_event['id'])
            if new_event is None or handoff_event(old_event, old_evidence) != handoff_event(new_event, new_evidence):
                raise ValueError('Existing handoff events/evidence must be preserved')
    old=(previous or {}).get('publicCase')
    new=(current or {}).get('publicCase')
    if old is None or (new is not None and old['status']==new['status']):return
    if new is None:raise ValueError('Removing a public case requires an explicit reviewed status first')
    evidence={e['id']:e for e in current['evidence']}
    review=new['review']
    if review is None or evidence.get(review['evidenceRef'],{}).get('kind')!='user_statement':
        raise ValueError('Public case status change requires explicit user review evidence')
