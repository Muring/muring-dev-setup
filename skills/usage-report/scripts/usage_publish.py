#!/usr/bin/env python3
"""Export existing aggregates to a blog. No local session logs or model calls."""
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import urllib.request

from usage_store import aggregate, atomic, now, read, TZ
from usage_report import stamp

TOKEN_KEYS = ('input', 'cache_read', 'cache_write', 'output', 'reasoning', 'responses', 'total', 'non_cache_read_input')
DIAGNOSTIC_KEYS = ('calls', 'outputs', 'output_chars', 'large_outputs', 'truncations', 'repeated_calls', 'known_failed_outputs', 'unknown_output_outcomes', 'kb_searches', 'kb_empty_searches', 'kb_selections', 'kb_applications', 'kb_search_mentions', 'compactions')
FATAL = {'incompatible_metrics', 'shard_integrity', 'request_conflict', 'event_conflict', 'no_successful_snapshot'}

def counts(source):
    return {key: source[key] for key in TOKEN_KEYS}

def export(worktree, sequence, revision, improvements=None):
    if sequence < 1 or not re.fullmatch(r'[0-9a-f]{40,64}', revision):
        raise ValueError('positive sequence and full source commit required')
    manifests = [read(p) for p in Path(worktree).glob('devices/*/manifest.json')]
    years = sorted({int(week[:4]) for m in manifests for week in m['shards']})
    if not years:
        raise ValueError('no source snapshots; refuse to replace published data')
    result = []
    for year in years:
        report = aggregate(worktree, year)
        if any(p['code'] in FATAL for p in report['quality']['problems']):
            raise ValueError('source integrity or metric version failure; preserving published snapshot')
        weeks = []
        devices = [{k: d.get(k) for k in ('device', 'since', 'until')} for d in report['devices']]
        for w in report['weeks']:
            start = stamp(w['week']).replace(tzinfo=TZ)
            end = min(start + timedelta(days=7), now())
            relevant = [d for d in devices if d['since'] and d['until'] and stamp(d['since']) < end and stamp(d['until']) > start]
            complete = bool(relevant) and all(stamp(d['since']) <= start and stamp(d['until']) >= end for d in relevant)
            weeks.append(dict(week=w['week'], ended=w['period_ended'], observed=w['observation']=='observed', partial=not complete,
                              totals=counts(w['totals']), groups=[dict(project=g['project'], tool=g['tool'], model=g['model'], effort=g['effort'], totals=counts(g)) for g in w['groups']],
                              states={k: counts(v) for k,v in w['task_states'].items()}, diagnostics={k:w['diagnostics'][k] for k in DIAGNOSTIC_KEYS}))
        # Missing calendar weeks stay unknown instead of joining adjacent points.
        if weeks:
            cursor = datetime.fromisoformat(weeks[0]['week']).replace(tzinfo=TZ)
            current = now().astimezone(TZ)
            current -= timedelta(days=current.weekday())
            last = current if current.year == year else datetime.fromisoformat(weeks[-1]['week']).replace(tzinfo=TZ)
            known = {w['week']: w for w in weeks}
            while cursor.date() <= last.date():
                key = cursor.date().isoformat()
                if key not in known:
                    weeks.append(dict(week=key, ended=cursor+timedelta(days=7)<=now(), observed=False, partial=True,
                                      totals={k:0 for k in TOKEN_KEYS}, groups=[], states={}, diagnostics={k:0 for k in DIAGNOSTIC_KEYS}))
                cursor += timedelta(days=7)
            weeks.sort(key=lambda w:w['week'])
        tasks = [dict(id=t['id'], project=t['project'], type=t.get('type'), status=t['status'], verification=t.get('verification') or [], rework=t.get('rework'), conflict=t['conflict'], totals=counts(t['totals'])) for t in report['tasks']]
        result.append(dict(year=year, weeks=weeks, devices=devices, tasks=tasks, quality={k:report['quality'][k] for k in ('problems','fallback_identities','task_conflicts','ambiguous_task_responses','comparison')},
                           fieldObservations=report['field_observation_counts']))
    return dict(schema=1, metrics='usage-v1', sequence=sequence, sourceRevision=revision, generatedAt=now().isoformat(), years=result,
                improvements=[{k:e[k] for k in ('date','kind','summary') if k in e} for e in improvements or []])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worktree',required=True);p.add_argument('--sequence',type=int,required=True)
    p.add_argument('--revision',required=True);p.add_argument('--output',required=True)
    p.add_argument('--improvements');p.add_argument('--send',action='store_true')
    args=p.parse_args()
    payload=export(args.worktree,args.sequence,args.revision,read(args.improvements,[]) if args.improvements else [])
    atomic(args.output,payload)
    if args.send:
        url=os.environ.get('AI_USAGE_INGEST_URL','');key=os.environ.get('AI_USAGE_INGEST_KEY','')
        if not url.startswith('https://') or len(key)<32: raise ValueError('HTTPS endpoint and ingestion key required')
        request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        with urllib.request.urlopen(request,timeout=60) as response:
            if response.status!=200: raise RuntimeError('snapshot delivery failed')
    print(json.dumps({'years':len(payload['years']),'weeks':sum(len(y['weeks']) for y in payload['years']),'sent':args.send}))
if __name__=='__main__':main()
