"""Immutable private reconciliation attempts, linked to exact decision/evidence snapshots."""
from copy import deepcopy
from pathlib import Path
import re

from usage_activity import validate as validate_activity, check_schema, parse_time
from usage_store import atomic, digest, read

KEYS = {'schemaVersion', 'id', 'project', 'taskId', 'reviewedAt', 'status', 'source', 'sourceDigest', 'result', 'error'}
SOURCE_KEYS = {'knowledgeDecisionsPresent', 'knowledgeDecisions', 'knowledge', 'evidence'}
STATES = {'matched', 'missing_application_record', 'not_applied', 'decision_unknown', 'uncollected',
          'broken_search_link', 'search_unavailable', 'not_recordable_document', 'document_missing',
          'application_decision_conflict', 'task_conflict', 'recorded'}
PATH = re.compile(r'devices/[^/]+/knowledge-reviews/([0-9a-f]{32})\.json')


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Invalid knowledge-review object fields')


def text(value, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-16-le')) // 2 > limit:
        raise ValueError('Invalid knowledge-review text')


def source_for(task):
    a = task.get('activity') or {}
    return deepcopy(dict(knowledgeDecisionsPresent='knowledgeDecisions' in a,
                         knowledgeDecisions=a.get('knowledgeDecisions'),
                         knowledge=a.get('knowledge'), evidence=a.get('evidence', [])))


def fingerprint(project, task_id, source):
    return digest(dict(project=project, id=task_id, source=source))


def validate_source(source):
    exact(source, SOURCE_KEYS)
    if type(source['knowledgeDecisionsPresent']) is not bool:
        raise ValueError('Knowledge decision presence must be boolean')
    if not source['knowledgeDecisionsPresent'] and source['knowledgeDecisions'] is not None:
        raise ValueError('Absent knowledge decisions must remain null')
    # Reuse the canonical activity schema and semantic checks without inferring work.
    a = {k: None for k in ('purpose', 'actions', 'aiRole', 'humanRole', 'outcomes',
                           'verification', 'followUps', 'knowledge', 'effects', 'publicCase')}
    a.update(schemaVersion=1, category='unknown', evidence=source['evidence'], knowledge=source['knowledge'],
             timing=dict(startedAt=None, endedAt=None, occurredAt=None, occurredOn=None,
                         precision='unknown', labelDate=None, basis='unknown', evidenceRefs=[]))
    if source['knowledgeDecisionsPresent']:
        a['knowledgeDecisions'] = source['knowledgeDecisions']
    validate_activity(a)


def validate_result(result, project, task_id, source):
    exact(result, {'schemaVersion', 'visibility', 'rows', 'recordingRequested', 'inferredApplications'})
    if type(result['schemaVersion']) is not int or result['schemaVersion'] != 1 or result['visibility'] != 'private':
        raise ValueError('Invalid KB review version/visibility')
    if type(result['recordingRequested']) is not bool or type(result['inferredApplications']) is not int or result['inferredApplications'] != 0:
        raise ValueError('Inferred KB applications are forbidden')
    rows = result['rows']
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Invalid KB review rows')
    decisions = source['knowledgeDecisions']
    by_document = {d['document']: d for d in decisions or []}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid KB review row')
        base = {'project', 'task', 'document', 'state'}
        if not base <= set(row) or row['project'] != project or row['task'] != task_id:
            raise ValueError('KB review row task identity mismatch')
        state, document = row['state'], row['document']
        if not isinstance(state, str) or state not in STATES:
            raise ValueError('Unknown KB review state')
        if document is None:
            exact(row, base)
            if len(rows) != 1 or state not in ('uncollected', 'task_conflict'):
                raise ValueError('Invalid task-level review row')
            if state == 'uncollected' and decisions is not None:
                raise ValueError('Collected decisions cannot be uncollected')
            return
        if not isinstance(document, str) or document not in by_document or document in seen:
            raise ValueError('Duplicate or unrelated KB review document')
        seen.add(document)
        required = base | {'decision', 'reason', 'searchLink'}
        if not required <= set(row) or set(row) - required - {'detail', 'applicationEvent'}:
            raise ValueError('Invalid document review fields')
        decision = by_document[document]
        if row['decision'] != decision['decision'] or row['reason'] != decision['reason']:
            raise ValueError('Review does not match its original knowledge decision')
        link = row['searchLink']
        if decision['selection'] == 'direct':
            valid_links = {'direct'}
        else:
            valid_links = {'linked', 'broken_search_link', 'search_unavailable'}
        if not isinstance(link, str) or link not in valid_links:
            raise ValueError('Review search link contradicts selection')
        if link in ('broken_search_link', 'search_unavailable'):
            allowed = {link}
        elif decision['decision'] == 'unknown':
            allowed = {'decision_unknown'}
        elif decision['decision'] != 'applied':
            allowed = {'not_applied', 'application_decision_conflict'}
        else:
            allowed = {'matched', 'missing_application_record', 'not_recordable_document', 'document_missing', 'recorded'}
        if state not in allowed:
            raise ValueError('KB review state contradicts source decision/link')
        if 'detail' in row:
            text(row['detail'], 2000)
            if state != 'not_recordable_document':
                raise ValueError('Unexpected KB review detail')
        if state == 'recorded' and 'applicationEvent' not in row:
            raise ValueError('Recorded review needs applicationEvent')
        if 'applicationEvent' in row:
            text(row['applicationEvent'], 2000)
            if state not in ('recorded', 'matched') or not result['recordingRequested']:
                raise ValueError('Unexpected application event')
    if decisions is None or seen != set(by_document):
        raise ValueError('KB review omitted original knowledge decisions')


def validate(value, project=None, task_id=None):
    exact(value, KEYS)
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
        raise ValueError('Invalid knowledge-review version')
    if not isinstance(value['id'], str) or not re.fullmatch('[0-9a-f]{32}', value['id']):
        raise ValueError('Invalid knowledge-review attempt id')
    text(value['project']); text(value['taskId'])
    if project is not None and (value['project'], value['taskId']) != (project, task_id):
        raise ValueError('Knowledge-review task identity mismatch')
    check_schema(value['reviewedAt'], {'type': 'string', 'maxLength': 300, 'format': 'date-time'})
    validate_source(value['source'])
    if value['sourceDigest'] != fingerprint(value['project'], value['taskId'], value['source']):
        raise ValueError('Knowledge-review source digest mismatch')
    if value['status'] == 'completed':
        if value['error'] is not None:
            raise ValueError('Completed review cannot hide an error')
        validate_result(value['result'], value['project'], value['taskId'], value['source'])
    elif value['status'] in ('failed', 'unavailable'):
        if value['result'] is not None:
            raise ValueError('Failed/unavailable review cannot carry a successful result')
        text(value['error'], 2000)
    else:
        raise ValueError('Unknown review execution status')
    return deepcopy(value)


def validate_reviews(values, task):
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError('Invalid knowledge-review history size')
    unique = {}
    for value in values:
        checked = validate(value, task['project'], task['id'])
        if checked['id'] in unique:
            raise ValueError('Duplicate knowledge-review id in task')
        unique[checked['id']] = checked
    if task.get('conflict') and values:
        raise ValueError('Knowledge-review target task conflict')
    return list(unique.values())


def merge_records(tasks, conflicts, records):
    groups = {}
    for name, value in records:
        match = PATH.fullmatch(name)
        checked = validate(value)
        if not match or match[1] != checked['id']:
            raise ValueError('Invalid knowledge-review path/attempt id')
        key = digest([checked['project'], checked['taskId']])
        if key not in tasks or key in conflicts or tasks[key].get('conflict'):
            raise ValueError('Missing/conflicting knowledge-review target')
        if checked['id'] in groups and groups[checked['id']] != checked:
            raise ValueError('Conflicting knowledge-review attempt')
        groups[checked['id']] = checked
    for checked in groups.values():
        key = digest([checked['project'], checked['taskId']])
        tasks[key].setdefault('knowledgeReviews', []).append(checked)
    for task in tasks.values():
        if 'knowledgeReviews' in task:
            task['knowledgeReviews'] = validate_reviews(task['knowledgeReviews'], task)
            task['knowledgeReviews'].sort(key=lambda v: (parse_time(v['reviewedAt']), v['id']))


def records_from(worktree):
    records = []
    for directory in sorted((Path(worktree) / 'devices').glob('*/knowledge-reviews')):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Invalid knowledge-review directory')
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise ValueError('Invalid knowledge-review file')
            records.append((path.relative_to(worktree).as_posix(), read(path)))
    return records


def persist(config, value):
    checked = validate(value)
    path = Path(config['worktree']) / 'devices' / config['device'] / 'knowledge-reviews' / (checked['id'] + '.json')
    old = read(path)
    if old is not None and old != checked:
        raise ValueError('Cannot replace an existing reconciliation attempt')
    from usage_store import aggregate
    tasks = [t for t in aggregate(config['worktree'])['tasks']
             if (t['project'], t['id']) == (checked['project'], checked['taskId'])]
    if len(tasks) != 1 or tasks[0].get('conflict'):
        raise ValueError('Missing/conflicting knowledge-review target')
    history = tasks[0].get('knowledgeReviews', [])
    duplicate = next((r for r in history if r['id'] == checked['id']), None)
    if duplicate is not None and duplicate != checked:
        raise ValueError('Conflicting knowledge-review attempt')
    validate_reviews(history if duplicate is not None else history + [checked], tasks[0])
    atomic(path, checked)
    return str(path)
