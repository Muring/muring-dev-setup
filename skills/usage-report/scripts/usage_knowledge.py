"""Private KB integration. KB owns search and application reconciliation semantics."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from usage_activity import validate
from usage_store import atomic, digest, now, read


def task_context(config, handle):
    if not re.fullmatch(r'[0-9a-f]{32}', handle):
        raise ValueError('use the handle returned by task-start')
    draft = read(Path(config['state']) / 'task-runs' / (handle + '.json'))
    if not draft:
        raise ValueError('unknown task handle')
    return draft


def search(config, handle, query, keyword=False, limit=3, project=None):
    draft = task_context(config, handle)
    if draft.get('result'):
        raise ValueError('start a new task interval before searching')
    # The KB telemetry contract currently reads only this default config.
    # Refuse a different target rather than silently linking another state store.
    telemetry = read(Path.home() / '.config/ai-workflow/tracking.json', {})
    if any(not telemetry.get(k) or Path(telemetry[k]).resolve() != Path(config[k]).resolve()
           for k in ('repo', 'state')):
        raise ValueError('KB telemetry must use the same repo/state in the default tracking configuration')
    command = [sys.executable, str(Path(config['repo']) / 'scripts/kb.py'), 'search',
               '--json', '--limit', str(limit), '--task-project', draft['project'], '--task-id', draft['id']]
    if keyword:
        command.append('--keyword')
    if project:
        command.extend(['--project', project])
    # Query travels only to the KB CLI; never persist it in tracker state/events.
    command.extend(['--', query])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode:
        raise ValueError('KB search failed; query and subprocess output were not recorded')
    return json.loads(completed.stdout)


def review(config, tasks, record_confirmed=False):
    for task in tasks:
        if 'activity' in task:
            validate(task['activity'], task['project'], task['id'])
    script = Path(config.get('repo', '')) / 'scripts/ai_work_records.py'
    if not script.is_file():
        return dict(state='unavailable', reason='KB knowledge-review CLI is unavailable', visibility='private')
    # A private temporary input is removed even when the KB validator fails.
    state = Path(config['state'])
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='knowledge-review-', dir=state) as directory:
        source = Path(directory) / 'tasks.json'
        atomic(source, dict(tasks=tasks))
        command = [sys.executable, str(script), 'knowledge-review', '--input', str(source),
                   '--kb-root', config['repo'], '--search-events', str(state / 'kb-events')]
        if record_confirmed:
            command.append('--record-confirmed')
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if completed.returncode:
            raise ValueError('KB knowledge-review failed; application history was not confirmed')
        return json.loads(completed.stdout)


def selection_events(config, task, document=None):
    activity = validate(task['activity'], task['project'], task['id']) if 'activity' in task else {}
    decisions = activity.get('knowledgeDecisions') or []
    if document is not None:
        decisions = [d for d in decisions if d['document'] == document]
        if not decisions:
            raise ValueError('kb-selection requires a stored knowledge decision for this document')
    events = []
    root = Path(config.get('repo', '')).resolve()
    for decision in decisions:
        # Unknown judgements without evidence do not establish an actual selection.
        if not decision['evidenceRefs']:
            continue
        location = (root / decision['document']).resolve()
        if not location.is_relative_to(root) or not location.is_file():
            continue
        key = digest(['kb_selection', task['project'], task['id'], decision['document']])
        path = Path(config['state']) / 'kb-events' / (key + '.json')
        event = dict(key=key, kind='kb_selection', document=decision['document'],
                     project=task['project'], task=task['id'], evidence_kind='explicit_record')
        previous = read(path)
        if previous is not None:
            if {k: v for k, v in previous.items() if k != 'timestamp'} != event:
                raise ValueError('conflicting KB selection event')
            events.append(previous)
        else:
            event['timestamp'] = now().isoformat()
            events.append(event)
    # Preflight every event before writing any, and retain the first observation time.
    for event in events:
        path = Path(config['state']) / 'kb-events' / (event['key'] + '.json')
        if not path.exists():
            atomic(path, event)
    return events
