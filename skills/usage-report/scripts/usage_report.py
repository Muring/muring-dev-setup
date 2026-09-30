#!/usr/bin/env python3
"""Read local request usage, never conversation bodies or credentials into the report."""
import argparse
import collections
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path, PureWindowsPath
from zoneinfo import ZoneInfo

FIELDS = ('input', 'cache_read', 'cache_write', 'output', 'reasoning')

def stamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None

def project(cwd):
    normalized = cwd.replace('\\', '/')
    if '/orca/workspaces/' in normalized:
        return normalized.split('/orca/workspaces/', 1)[1].split('/')[0]
    return normalized.rstrip('/').rsplit('/', 1)[-1] or 'unknown'

def rows(path, warnings):
    try:
        with path.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                try:
                    yield number, json.loads(line)
                except (ValueError, UnicodeError):
                    warnings.append(f'{path}:{number}: unreadable JSON record (possibly active write)')
    except OSError as error:
        warnings.append(f'{path}: {error.strerror}')

def collect(roots, start, end):
    records, sessions, warnings = {}, {}, []
    stats = collections.Counter()
    def inside(t): return t is not None and start <= t < end
    def put(key, record):
        if key in records:
            stats['duplicate_records'] += 1
            # Streaming blocks repeat cumulative usage for one response.
            old = records[key]
            for field in FIELDS:
                record[field] = max(old[field], record[field])
            record['observed_fields'] = sorted(set(old.get('observed_fields', [])) | set(record.get('observed_fields', [])))
        records[key] = record
    visited = set()
    for tool, root in roots:
        if not root.exists():
            warnings.append(f'{root}: log root missing')
            continue
        for path in ([root] if root.is_file() else sorted(root.rglob('*.jsonl'))):
            identity = str(path.resolve())
            if identity in visited:
                continue
            visited.add(identity)
            stats['files'] += 1
            # Metadata-only pass decides authoritative Codex accounting source.
            has_records, meta, cwd = False, {}, ''
            legacy_before_records = False
            data = list(rows(path, warnings))
            for _, d in data:
                if d.get('type') == 'session_meta':
                    meta = d.get('payload', {})
                    cwd = meta.get('cwd', cwd)
                if d.get('type') == 'token_usage_record': has_records = True
                elif not has_records and d.get('type') == 'event_msg':
                    payload = d.get('payload') or {}
                    info = payload.get('info') or {}
                    if payload.get('type') == 'token_count' and any((info.get('total_token_usage') or {}).values()):
                        legacy_before_records = True
                cwd = cwd or d.get('cwd', '')
                if d.get('sessionId') and not meta.get('id'): meta['id'] = d['sessionId']
            if has_records and legacy_before_records:
                warnings.append(f'{path}: mixed legacy usage before request records; historical coverage uncertain')
            sid = meta.get('id', path.stem)
            model, effort, previous, active = 'unknown', 'unknown', None, False
            for line, d in data:
                t = stamp(d.get('timestamp'))
                v = d.get('payload') or {}
                if tool == 'Codex' and d.get('type') == 'turn_context':
                    model = v.get('model', model)
                    effort = v.get('effort') or v.get('reasoning_effort') or 'unknown'
                usage, key = None, None
                if tool == 'Codex':
                    if d.get('type') == 'token_usage_record' and inside(t):
                        usage = v.get('usage')
                        key = ('Codex', v.get('response_id') or f'{sid}:{line}')
                    elif not has_records and d.get('type') == 'event_msg' and v.get('type') == 'token_count' and v.get('info'):
                        info = v['info']; total = info.get('total_token_usage') or {}
                        if inside(t):
                            if previous is None and not inside(stamp(meta.get('timestamp'))):
                                warnings.append(f'{path}:{line}: missing period baseline; only last usage counted')
                                usage = info.get('last_token_usage')
                            else:
                                usage = {k: value - (previous or {}).get(k, 0) for k, value in total.items()}
                                if any(x < 0 for x in usage.values()):
                                    warnings.append(f'{path}:{line}: cumulative counter reset; only last usage counted')
                                    usage = info.get('last_token_usage')
                            key = ('Codex-fallback', sid, line)
                        previous = total
                    if usage:
                        values = dict(input=usage.get('input_tokens', 0), cache_read=usage.get('cached_input_tokens', 0), cache_write=usage.get('cache_write_input_tokens', 0), output=usage.get('output_tokens', 0), reasoning=usage.get('reasoning_output_tokens', 0))
                elif d.get('type') == 'assistant' and inside(t):
                    message = d.get('message') or {}
                    usage = message.get('usage')
                    if usage and message.get('id') and message.get('model') != '<synthetic>':
                        model = message.get('model', 'unknown')
                        effort = d.get('perTurnEffort') or d.get('effort') or 'unknown'
                        key = ('Claude', d.get('requestId'), message['id'])
                        values = dict(input=usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0), cache_read=usage.get('cache_read_input_tokens', 0), cache_write=usage.get('cache_creation_input_tokens', 0), output=usage.get('output_tokens', 0), reasoning=(usage.get('output_tokens_details') or {}).get('thinking_tokens', 0))
                if key and usage and values['input'] + values['output']:
                    field_names = dict(input='input_tokens', output='output_tokens', cache_read='cached_input_tokens' if tool == 'Codex' else 'cache_read_input_tokens', cache_write='cache_write_input_tokens' if tool == 'Codex' else 'cache_creation_input_tokens', reasoning='reasoning_output_tokens')
                    observed_fields = [field for field, name in field_names.items() if name in usage]
                    if tool == 'Claude' and 'thinking_tokens' in (usage.get('output_tokens_details') or {}):
                        observed_fields.append('reasoning')
                    active = True
                    put(key, dict(observed_fields=sorted(observed_fields), request_key=hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest(), identity_quality='strong' if (tool == 'Claude' or (key[0] == 'Codex' and v.get('response_id'))) else 'fallback', effort=effort, tool=tool, session=sid, cwd=cwd, project=project(cwd), model=model, timestamp=t.isoformat(), source=str(path), line=line, **values))
                if inside(t) and d.get('type') == 'compacted': stats['codex_compactions'] += 1
                if tool == 'Claude' and d.get('type') == 'cost-state': stats['claude_cost_snapshots_not_added'] += 1
            if active:
                sessions[(tool, sid)] = dict(tool=tool, session=sid, cwd=cwd, source=str(path), subagent='/subagents/' in path.as_posix())
    return list(records.values()), list(sessions.values()), stats, warnings

def summarize(records, key):
    groups = {}
    for row in records:
        label = row[key]
        g = groups.setdefault(label, dict(label=label, responses=0, **{k: 0 for k in FIELDS}))
        g['responses'] += 1
        for field in FIELDS: g[field] += row[field]
    for g in groups.values():
        g['non_cache_read_input'] = g['input'] - g['cache_read']
        g['total'] = g['input'] + g['output']
        g['cache_read_percent'] = round(g['cache_read'] * 100 / g['input'], 2) if g['input'] else 0
    return sorted(groups.values(), key=lambda g: -g['total'])

def diagnose(records, start, end, warnings):
    """Inspect tool metadata locally; never return arguments, output, or messages."""
    codex = [r for r in records if r['tool'] == 'Codex']
    inputs = sorted(r['input'] for r in records)
    totals = collections.Counter()
    tools = collections.Counter()
    nested = collections.Counter()
    signatures = collections.Counter()
    seen = set()
    def output_text(value):
        if isinstance(value, str): return value
        if isinstance(value, list):
            return '\n'.join(x.get('text', '') for x in value if isinstance(x, dict) and isinstance(x.get('text', ''), str))
        return ''
    for source in sorted({r['source'] for r in codex}):
        for line, d in rows(Path(source), warnings):
            t = stamp(d.get('timestamp'))
            if t is None or not start <= t < end: continue
            v = d.get('payload') or {}
            if d.get('type') == 'compacted': totals['compactions'] += 1
            if d.get('type') == 'turn_context': totals['turn_context_records'] += 1
            if d.get('type') != 'response_item': continue
            kind = v.get('type')
            if kind not in ('function_call', 'custom_tool_call', 'function_call_output', 'custom_tool_call_output'): continue
            identity = (kind, v.get('call_id') or (source, line))
            if identity in seen: continue
            seen.add(identity)
            if kind in ('function_call', 'custom_tool_call'):
                name = v.get('name', 'unknown')
                tools[name] += 1
                arguments = v.get('arguments', v.get('input', ''))
                if not isinstance(arguments, str): arguments = json.dumps(arguments, sort_keys=True)
                signatures[(source, name, hashlib.sha256(arguments.encode()).digest())] += 1
                # Code-mode wrappers expose nested names, not nested execution outcomes.
                nested.update(re.findall(r'\btools\.([A-Za-z_][A-Za-z_0-9]*)\s*\(', arguments))
                totals['tool_calls'] += 1
                totals['tool_argument_chars'] += len(arguments)
            else:
                text = output_text(v.get('output'))
                totals['tool_outputs'] += 1
                totals['tool_output_chars'] += len(text)
                totals['outputs_over_8000_chars'] += len(text) > 8000
                totals['truncation_markers'] += bool(re.search(r'output (?:was )?truncated|Warning: truncated output|tokens truncated', text, re.I))
    repeated = collections.Counter()
    for (_, name, _), count in signatures.items():
        if count > 1: repeated[name] += count - 1
    claude_sources = {r['source'] for r in records if r['tool'] == 'Claude'}
    if claude_sources:
        from usage_store import observations
        events = {}
        for source in sorted(claude_sources):
            found, problems = observations('Claude', Path(source), start, end)
            warnings.extend(problems)
            events.update({event['key']: event for event in found})
        for event in events.values():
            if event['kind'] == 'call':
                tools[event['name']] += 1
                totals['tool_calls'] += 1
                totals['tool_argument_chars'] += event['chars']
                repeated[event['name']] += event['repeated']
            elif event['kind'] == 'output':
                totals['tool_outputs'] += 1
                totals['tool_output_chars'] += event['chars']
                totals['outputs_over_8000_chars'] += event['large']
                totals['truncation_markers'] += event['truncated']
            elif event['kind'] == 'compaction':
                totals['compactions'] += 1
    return dict(**totals, input_tokens_per_response=dict(
        median=inputs[len(inputs)//2] if inputs else 0,
        p90=inputs[min(len(inputs)-1, int(len(inputs)*.9))] if inputs else 0,
        maximum=max(inputs, default=0)),
        tool_names=dict(tools.most_common()), nested_tool_mentions=dict(nested.most_common()),
        repeated_exact_calls=dict(repeated.most_common()),
        scope='Codex and Claude observable tool metadata only. Character counts are not token counts. Nested mentions are not executed-call counts. Repeated calls may be necessary polling or verification; these are review signals, not measured waste or savings.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    period = parser.add_mutually_exclusive_group()
    period.add_argument('--week', action='store_true', help='current Monday to now (default)')
    period.add_argument('--since', help='inclusive ISO date/time')
    period.add_argument('--days', type=int, help='rolling N days ending at --until or now')
    parser.add_argument('--tool', choices=['all', 'codex', 'claude'], default='all', help='filter log roots before reading')
    parser.add_argument('--diagnostics', action='store_true', help='aggregate Codex/Claude tool metadata without exposing content')
    parser.add_argument('--until', help='exclusive ISO date/time; default now')
    parser.add_argument('--timezone', default='Asia/Seoul')
    parser.add_argument('--home', action='append', help='client home, repeat for WSL/Windows; overrides saved homes')
    parser.add_argument('--codex-root', action='append', help='additional sessions/archived_sessions directory')
    parser.add_argument('--claude-root', action='append', help='additional projects directory')
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'ai-workflow/usage.json')
    parser.add_argument('--by', default='project,tool', help='comma-separated project,tool,session,cwd,model,day')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    tz = ZoneInfo(args.timezone)
    def boundary(value):
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=tz)
    end = boundary(args.until) if args.until else datetime.now(tz)
    if args.days is not None and args.days < 1: parser.error('--days must be positive')
    start = boundary(args.since) if args.since else end - timedelta(days=args.days) if args.days else (end - timedelta(days=end.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if start >= end: parser.error('--since must precede --until')
    keys = args.by.split(',')
    if args.limit < 1 or any(k not in ('project','tool','session','cwd','model','day') for k in keys): parser.error('invalid --by or --limit')
    config = json.loads(args.config.read_text()) if args.config.exists() else {}
    homes = [Path(x).expanduser() for x in (args.home or config.get('homes') or [str(Path.home())])]
    roots = []
    for home in homes:
        codex = Path(os.environ.get('CODEX_HOME', home/'.codex')) if home == Path.home() else home/'.codex'
        claude = Path(os.environ.get('CLAUDE_CONFIG_DIR', home/'.claude')) if home == Path.home() else home/'.claude'
        roots.extend([('Codex', codex/'sessions'), ('Claude', claude/'projects')])
        if (codex/'archived_sessions').exists(): roots.append(('Codex', codex/'archived_sessions'))
    roots += [('Codex', Path(x).expanduser()) for x in args.codex_root or []]
    roots += [('Claude', Path(x).expanduser()) for x in args.claude_root or []]
    roots = [(tool, root) for tool, root in roots if args.tool == 'all' or tool.lower() == args.tool]
    records, sessions, stats, warnings = collect(roots, start, end)
    for row in records: row['day'] = stamp(row['timestamp']).astimezone(tz).date().isoformat()
    totals = summarize([{**r, 'all':'all'} for r in records], 'all')
    result = dict(period=dict(since=start.isoformat(), until=end.isoformat(), timezone=args.timezone), totals=totals[0] if totals else {}, sessions=len(sessions), scanned=dict(stats), roots=[dict(tool=t,path=str(p)) for t,p in roots], groups={k:summarize(records,k)[:args.limit] for k in keys}, group_limit=args.limit, warnings=warnings, scope='Locally observed request usage, not billing or quota. Cache writes are included in input; reasoning is included in output. Claude cost-state/internal requests, image backend charges and unavailable logs are not added. Project grouping uses session cwd.')
    if args.diagnostics: result['diagnostics'] = diagnose(records, start, end, warnings)
    if args.json: print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f'{start.isoformat()} .. {end.isoformat()} (end exclusive)')
        print(f'{len(sessions)} sessions / {len(records):,} responses / {(totals[0]["total"] if totals else 0):,} tokens')
        for key, groups in result['groups'].items():
            print(f'\n{key}: total | non-cache-read input | output')
            for g in groups: print(f'{g["label"]}: {g["total"]:,} | {g["non_cache_read_input"]:,} | {g["output"]:,}')
        print('\n'+result['scope'])
        if args.diagnostics: print('\n'+json.dumps(result['diagnostics'], ensure_ascii=False, indent=2))
        for warning in warnings: print('Warning: '+warning)

if __name__ == '__main__': main()
