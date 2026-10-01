"""Versioned, content-only usage records. No model calls or network access."""
import collections
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

import usage_report as legacy

SCHEMA = 1
METRICS = 'usage-v1'
TZ = ZoneInfo('Asia/Seoul')
FIELDS = legacy.FIELDS

def now():
    return datetime.now(timezone.utc)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return True

@contextmanager
def lock(state):
    """OS-released lock: a crash does not leave a stale sentinel."""
    path = Path(state) / 'runner.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if os.name == 'nt':
            import msvcrt
            f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise RuntimeError('collector already running') from e
        else:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise RuntimeError('collector already running') from e
        try:
            yield
        finally:
            if os.name == 'nt':
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)

def week(ts):
    day = legacy.stamp(ts).astimezone(TZ).date()
    return (day - timedelta(days=day.weekday())).isoformat()

def token_totals(rows):
    counts = {f: sum(r[f] for r in rows) for f in FIELDS}
    return dict(counts, responses=len(rows), total=counts['input'] + counts['output'],
                non_cache_read_input=counts['input'] - counts['cache_read'])

def valid_usage(r):
    return (all(isinstance(r.get(f), int) and not isinstance(r[f], bool) and r[f] >= 0 for f in FIELDS)
            and r['cache_read'] + r['cache_write'] <= r['input'] and r['reasoning'] <= r['output'])

def observations(tool, path, start, end):
    """Extract only observable facts; argument signatures never leave this function."""
    result, warnings, repeated = {}, [], collections.Counter()
    sid = path.stem
    for line, row in legacy.rows(path, warnings):
        payload = row.get('payload') or {}
        if row.get('type') == 'session_meta':
            sid = payload.get('id', sid)
        sid = row.get('sessionId') or sid
        ts = legacy.stamp(row.get('timestamp'))
        if ts is None or not start <= ts < end:
            continue
        blocks = []
        if tool == 'Codex' and row.get('type') == 'response_item':
            kind = payload.get('type')
            if kind in ('function_call', 'custom_tool_call'):
                blocks = [('call', payload.get('call_id'), payload.get('name', 'unknown'), payload.get('arguments', payload.get('input', '')), False)]
            elif kind in ('function_call_output', 'custom_tool_call_output'):
                blocks = [('output', payload.get('call_id'), 'unknown', payload.get('output'), None)]
        elif tool == 'Claude':
            for block in (row.get('message') or {}).get('content', []):
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'tool_use':
                    blocks.append(('call', block.get('id'), block.get('name', 'unknown'), block.get('input', {}), False))
                elif block.get('type') == 'tool_result':
                    blocks.append(('output', block.get('tool_use_id'), 'unknown', block.get('content', ''), block.get('is_error')))
        if row.get('type') == 'compacted' or (row.get('type') == 'system' and row.get('subtype') == 'compact_boundary'):
            blocks.append(('compaction', str(line), 'unknown', '', False))
        for index, (kind, call, name, content, failed) in enumerate(blocks):
            key = digest([tool, sid, kind, call or [row.get('timestamp'), line, index]])
            if key in result:
                continue
            if isinstance(content, list):
                content = '\n'.join(x.get('text', '') for x in content if isinstance(x, dict))
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            event = dict(key=key, tool=tool, session=digest([tool, sid]), timestamp=ts.astimezone(timezone.utc).isoformat(), kind=kind)
            if kind == 'call':
                signature = digest([sid, name, content])
                event.update(name=name if re.fullmatch(r'[\w.:-]{1,160}', name) else 'unknown', chars=len(content), repeated=repeated[signature] > 0)
                repeated[signature] += 1
                # These are mentions in the outer call, not proof of nested execution.
                if re.search(r'\bmkb\s+search\b|\bkb\.py\s+search\b', content):
                    event['kb_search_mention'] = 'keyword' if '--keyword' in content else 'semantic_or_default'
            elif kind == 'output':
                exit_match = re.search(r'Process exited with code\s+(\d+)|"exit_code"\s*:\s*(\d+)', content)
                try:
                    structured = json.loads(content)
                    if isinstance(structured, dict) and isinstance(structured.get('exit_code'), int):
                        failed = structured['exit_code'] != 0
                except (ValueError, TypeError):
                    pass
                event['exit_failure_signal'] = bool(exit_match and int(next(x for x in exit_match.groups() if x is not None)) != 0)
                event.update(chars=len(content), large=len(content) > 8000,
                             truncated=bool(re.search(r'output (?:was )?truncated|Warning: truncated output|tokens truncated', content, re.I)), failed=failed)
            result[key] = event
    return list(result.values()), warnings

def resolve_project(cwd, projects):
    """Explicit absolute ancestors win, longest first; basename is a fallback."""
    def canonical(value):
        value = value.replace('\\', '/').rstrip('/')
        return value.casefold() if re.match(r'^[A-Za-z]:/', value) else value
    path = canonical(cwd)
    matches = [(len(canonical(root)), alias) for root, alias in projects.items()
               if (root.startswith('/') or re.match(r'^[A-Za-z]:[/\\]', root))
               and (path == canonical(root) or path.startswith(canonical(root) + '/'))]
    project = max(matches)[1] if matches else projects.get(cwd, projects.get(legacy.project(cwd), 'unmapped'))
    if not re.fullmatch(r'[a-zA-Z0-9_.\-/]{1,120}', project) or '..' in project:
        raise ValueError('invalid project identifier')
    return project

def valid_interval(interval):
    if not isinstance(interval, dict) or set(interval) != {'session', 'project', 'since', 'until'}:
        return False
    start, end = legacy.stamp(interval['since']), legacy.stamp(interval['until'])
    return (isinstance(interval['session'], str) and bool(re.fullmatch('[0-9a-f]{64}', interval['session']))
            and isinstance(interval['project'], str)
            and bool(re.fullmatch(r'[a-zA-Z0-9_./-]{1,120}', interval['project'])) and '..' not in interval['project']
            and start is not None and end is not None and start < end
            and all(isinstance(interval[k], str) and datetime.fromisoformat(interval[k].replace('Z', '+00:00')).tzinfo is not None
                    for k in ('since', 'until')))

def task_intervals(task):
    if 'intervals' in task:
        return [i for i in task['intervals'] if valid_interval(i)] if isinstance(task['intervals'], list) else []
    # Legacy unbounded sessions are not evidence of task boundaries.
    intervals = [dict(session=s, project=task['project'], since=task.get('since'), until=task.get('until'))
                 for s in task.get('sessions', [])]
    return [i for i in intervals if valid_interval(i)]

def normalize(r, projects):
    project = resolve_project(r['cwd'], projects)
    return dict(key=r['request_key'], observed_fields=r.get('observed_fields', []), identity_quality=r['identity_quality'], session=digest([r['tool'], r['session']]),
                timestamp=legacy.stamp(r['timestamp']).astimezone(timezone.utc).isoformat(),
                tool=r['tool'], project=project, model=r['model'], effort=r.get('effort', 'unknown'),
                **{f: r[f] for f in FIELDS})

def merge_requests(rows):
    merged, conflicts, fallback = {}, set(), set()
    for r in rows:
        if r.get('identity_quality') != 'strong':
            fallback.add(r['key'])
        old = merged.get(r['key'])
        if old and old != r:
            conflicts.add(r['key'])
            continue
        merged[r['key']] = r
    # Conflicted records are excluded from certified sums, not arbitrarily selected.
    return [r for key, r in merged.items() if key not in conflicts], sorted(conflicts), len(fallback)

def scan(config):
    started = time.monotonic()
    state = Path(config['state'])
    initial = now().astimezone(TZ) - timedelta(days=30)
    initial = (initial - timedelta(days=initial.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    cache = read(state / 'source-cache.json', {'files': {}, 'since': initial.isoformat()})
    start, end = legacy.stamp(cache['since']), now()
    files, seen, issues, roots = cache['files'], set(), [], []
    scanned = 0
    parser_fingerprint = digest([Path(legacy.__file__).read_text(), Path(__file__).read_text(), config['projects']])
    for root in config['roots']:
        path = Path(root['path']).expanduser()
        roots.append(dict(tool=root['tool'], available=path.is_dir()))
        if not path.is_dir():
            if root.get('required', True):
                issues.append(dict(code='root_unavailable', root=digest(str(path))))
            continue
        try:
            paths = sorted(path.rglob('*.jsonl'))
            for source in paths:
                key = str(source.resolve())
                if key in seen:
                    continue
                seen.add(key)
                stat = source.stat()
                fingerprint = [stat.st_size, stat.st_mtime_ns]
                old = files.get(key)
                if old and old['fingerprint'] == fingerprint and old.get('parser') == parser_fingerprint:
                    continue
                scanned += 1
                records, _, _, warnings = legacy.collect([(root['tool'], source)], start, end)
                events, event_warnings = observations(root['tool'], source, start, end)
                current = [normalize(r, config['projects']) for r in records]
                after = source.stat()
                if warnings or event_warnings or [after.st_size, after.st_mtime_ns] != fingerprint:
                    issues.append(dict(code='source_unstable_or_unreadable', source=digest(key), count=len(warnings) + len(event_warnings)))
                    continue
                if any(not valid_usage(r) for r in current):
                    issues.append(dict(code='invalid_usage', source=digest(key)))
                    continue
                if old:
                    before = {r['key']: r for r in old['records']}
                    present = {r['key']: r for r in current}
                    removed = set(before) - set(present)
                    decreased = [k for k in before.keys() & present.keys() if any(present[k][f] < before[k][f] for f in FIELDS)]
                    if stat.st_size < old['fingerprint'][0] or removed or decreased:
                        candidate = dict(source=digest(key), previous=digest(old['records']), records=current, events=events, fingerprint=fingerprint, metrics=METRICS, parser=parser_fingerprint, observed_at=end.isoformat())
                        atomic(state / 'quarantine' / (digest(key) + '.json'), candidate)
                        issues.append(dict(code='source_regression', source=digest(key)))
                        continue
                files[key] = dict(fingerprint=fingerprint, metrics=METRICS, parser=parser_fingerprint, records=current, events=events)
        except (OSError, ValueError, TypeError, KeyError) as error:
            issues.append(dict(code='source_scan_error', root=digest(str(path)), error_type=type(error).__name__))
    active_records = {digest(r) for key in seen if key in files for r in files[key]['records']}
    active_events = {digest(e) for key in seen if key in files for e in files[key]['events']}
    for key in files.keys() - seen:
        old = files[key]
        # A byte-equivalent observed record set at another path is a relocation,
        # not lost coverage (e.g. Codex sessions -> archived_sessions).
        relocated = (all(digest(r) in active_records for r in old['records']) and
                     all(digest(e) in active_events for e in old['events']))
        if not relocated:
            issues.append(dict(code='source_missing_preserved', source=digest(key)))
    # Safe per-source successes are retained locally even when another source fails.
    atomic(state / 'source-cache.json', cache)
    records, conflicts, fallback = merge_requests([r for f in files.values() for r in f['records']])
    if conflicts:
        issues.append(dict(code='request_conflict', count=len(conflicts)))
    events = {e['key']: e for f in files.values() for e in f['events']}
    for path in (state / 'kb-events').glob('*.json'):
        try:
            event = read(path)
            if start <= legacy.stamp(event['timestamp']) < end:
                events[event['key']] = event
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(dict(code='kb_event_unreadable'))
    for path in (Path(config.get('repo', state)) / 'usage/events').glob('*.json'):
        try:
            original = read(path)
            ts = legacy.stamp(original['recorded_at'])
            if start <= ts < end:
                key = digest(['kb_application', original['document'], original['project'], original['task']])
                events[key] = dict(key=key, kind='kb_application', timestamp=ts.isoformat(),
                                  document=original['document'], project=original['project'], task=original['task'], evidence_kind='explicit_record')
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(dict(code='kb_application_unreadable'))
    snapshot = dict(schema=SCHEMA, metrics=METRICS, device=config['device'], since=cache['since'], until=end.isoformat(),
                    records=sorted(records, key=lambda r: (r['timestamp'], r['key'])), events=sorted(events.values(), key=lambda r: (r['timestamp'], r['key'])))
    quality = dict(attempt=end.isoformat(), state='attention' if issues else 'observed', issues=issues, roots=roots,
                   files_seen=len(seen), files_parsed=scanned, fallback_identities=fallback,
                   duration_seconds=round(time.monotonic() - started, 3), collector=parser_fingerprint, metrics=METRICS)
    atomic(state / 'last-scan.json', quality)
    if not issues:
        atomic(state / 'last-good.json', snapshot)
    return snapshot, quality

def publish(config, snapshot, quality):
    """One immutable generation pointer makes multi-file publication transactional."""
    base = Path(config['worktree']) / 'devices' / config['device']
    existing = read(base / 'manifest.json', {})
    if quality['issues']:
        atomic(base / 'health.json', quality)
        return False
    grouped = {}
    first = legacy.stamp(snapshot['since']).astimezone(TZ).date()
    last = legacy.stamp(snapshot['until']).astimezone(TZ).date()
    day = first - timedelta(days=first.weekday())
    while day <= last:
        grouped[day.isoformat()] = dict(schema=SCHEMA, metrics=METRICS, week=day.isoformat(), records=[], events=[])
        day += timedelta(days=7)
    for kind in ('records', 'events'):
        for r in snapshot[kind]:
            grouped[week(r['timestamp'])][kind].append(r)
    shards = {}
    for monday, data in grouped.items():
        groups = collections.defaultdict(list)
        for record in data['records']:
            groups[(record['tool'], record['project'], record['model'], record['effort'])].append(record)
        data['summary'] = dict(totals=token_totals(data['records']), groups=[dict(tool=k[0], project=k[1], model=k[2], effort=k[3], **token_totals(v)) for k,v in sorted(groups.items())])
        fingerprint = digest(data)
        relative = f'{monday[:4]}/{monday}/{fingerprint}.json'
        atomic(base / relative, data)
        shards[monday] = dict(path=relative, hash=fingerprint)
    manifest = dict(schema=SCHEMA, metrics=METRICS, device=config['device'], since=snapshot['since'], until=snapshot['until'], shards=shards,
                    previous=digest(existing) if existing else None)
    # Manifests are versioned by Git; shard contents remain recoverable.
    if {k:v for k,v in existing.items() if k != 'previous'} != {k:v for k,v in manifest.items() if k != 'previous'}:
        atomic(base / 'manifest.json', manifest)
    atomic(base / 'health.json', quality)
    return True

def aggregate(worktree, year=None):
    worktree = Path(worktree)
    records, events, devices, problems = [], {}, [], []
    for base in sorted((worktree / 'devices').glob('*')):
        if not base.is_dir():
            continue
        manifest = read(base / 'manifest.json')
        health = read(base / 'health.json', {})
        devices.append(dict(device=base.name, until=manifest.get('until') if manifest else None, since=manifest.get('since') if manifest else None, health=health))
        if health.get('state') != 'observed':
            problems.append(dict(device=base.name, code='collection_attention'))
        if manifest and now() - legacy.stamp(manifest['until']) > timedelta(hours=48):
            problems.append(dict(device=base.name, code='stale_device'))
        if not manifest:
            problems.append(dict(device=base.name, code='no_successful_snapshot'))
            continue
        if manifest.get('schema') != SCHEMA or manifest.get('metrics') != METRICS:
            problems.append(dict(device=base.name, code='incompatible_metrics'))
            continue
        for entry in manifest['shards'].values():
            path = (base / entry['path']).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError('invalid shard path')
            shard = read(path)
            if not shard or digest(shard) != entry['hash']:
                problems.append(dict(device=base.name, code='shard_integrity'))
                continue
            records.extend(shard['records'])
            for e in shard['events']:
                if e['key'] in events and events[e['key']] != e:
                    problems.append(dict(device=base.name, code='event_conflict'))
                else:
                    events[e['key']] = e
    if year is not None:
        records = [r for r in records if week(r['timestamp']).startswith(str(year))]
        events = {k:e for k,e in events.items() if week(e['timestamp']).startswith(str(year))}
    rows, conflicts, fallback = merge_requests(records)
    if conflicts:
        problems.append(dict(code='request_conflict', count=len(conflicts)))
    tasks, task_conflicts = {}, set()
    for base in sorted((worktree / 'devices').glob('*')):
        for path in (base / 'tasks').glob('*.json'):
            task = read(path)
            key = digest([task['project'], task['id']])
            if key in tasks and tasks[key] != task:
                task_conflicts.add(key)
            else:
                tasks[key] = task
    intervals = {key: task_intervals(task) for key, task in tasks.items()}
    sessions = collections.defaultdict(set)
    for key, task in tasks.items():
        if key not in task_conflicts:
            for interval in intervals[key]:
                sessions[interval['session']].add(key)
    def linked_tasks(record):
        return {key for key in sessions.get(record['session'], set())
                if any(i['session'] == record['session'] and i['project'] == record['project']
                       and legacy.stamp(i['since']) <= legacy.stamp(record['timestamp']) < legacy.stamp(i['until'])
                       for i in intervals[key])}
    associations = {r['key']: linked_tasks(r) for r in rows}
    buckets = {}
    for device in devices:
        manifest = read(worktree / 'devices' / device['device'] / 'manifest.json', {})
        for monday in manifest.get('shards', {}):
            if year is None or monday.startswith(str(year)):
                buckets.setdefault(monday, [])
    for r in rows:
        buckets.setdefault(week(r['timestamp']), []).append(r)
    weeks = []
    for monday, members in sorted(buckets.items()):
        groups = collections.defaultdict(list)
        states = collections.defaultdict(list)
        for r in members:
            groups[(r['tool'], r['project'], r['model'], r['effort'])].append(r)
            linked = associations[r['key']]
            state = tasks[next(iter(linked))]['status'] if len(linked) == 1 else 'unclassified'
            states[state].append(r)
        observed = [e for e in events.values() if week(e['timestamp']) == monday]
        calls = [e for e in observed if e['kind'] == 'call']
        outputs = [e for e in observed if e['kind'] == 'output']
        diagnostics = dict(calls=len(calls), outputs=len(outputs), output_chars=sum(e['chars'] for e in outputs),
                           large_outputs=sum(e['large'] for e in outputs), truncations=sum(e['truncated'] for e in outputs),
                           repeated_calls=sum(e['repeated'] for e in calls), known_failed_outputs=sum(e.get('failed') is True for e in outputs),
                           unknown_output_outcomes=sum(e.get('failed') is None for e in outputs),
                           kb_search_mentions=sum('kb_search_mention' in e for e in calls),
                           kb_searches=sum(e['kind'] == 'kb_search' for e in observed),
                           kb_empty_searches=sum(e['kind'] == 'kb_search' and e['result_count'] == 0 for e in observed),
                           kb_applications=sum(e['kind'] == 'kb_application' for e in observed),
                           kb_selections=sum(e['kind'] == 'kb_selection' for e in observed),
                           compactions=sum(e['kind'] == 'compaction' for e in observed))
        wstart = datetime.fromisoformat(monday).replace(tzinfo=TZ)
        weeks.append(dict(week=monday, period_ended=wstart + timedelta(days=7) <= now(),
                          observation='observed' if members else 'no_records', totals=token_totals(members),
                          groups=[dict(tool=k[0], project=k[1], model=k[2], effort=k[3], **token_totals(v)) for k, v in sorted(groups.items())],
                          task_states={k: token_totals(v) for k, v in states.items()}, diagnostics=diagnostics))
    task_summaries = []
    for key, task in sorted(tasks.items()):
        members = [r for r in rows if associations[r['key']] == {key}]
        task_summaries.append(dict(task, totals=token_totals(members), conflict=key in task_conflicts,
                                   linkage='bounded' if intervals[key] else 'unknown',
                                   settings=sorted({(r['tool'], r['model'], r['effort']) for r in members})))
    return dict(schema=SCHEMA, metrics=METRICS, generated_at=now().isoformat(), devices=devices, weeks=weeks,
                quality=dict(problems=problems, fallback_identities=fallback, task_conflicts=len(task_conflicts), ambiguous_task_responses=sum(len(v)>1 for v in associations.values()), comparison='withheld'),
                totals=token_totals(rows), field_observation_counts={field:sum(field in r.get('observed_fields', []) for r in rows) for field in FIELDS}, tasks=task_summaries,
                limitations=['Local observations, not billing or subscription quota.', 'Repeated calls and KB mentions are review signals, not measured waste or savings.',
                             'Unreported tasks, verification and KB applications remain unknown.',
                             'Task totals with unknown linkage are unassigned observations, not measured zero usage.'])
