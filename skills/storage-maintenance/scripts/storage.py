#!/usr/bin/env python3
"""Read-only storage snapshots and explicitly approved exact-path maintenance."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import time
import uuid

from safety import activity_linux, canonical, delete_linux, digest, inspect_linux, inside, native_linux, policy_guard

SCRIPT = Path(__file__).resolve()
DEFAULT_STATE = Path.home() / '.local/state/storage-audit'


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')) or b'\x00' in data[:100]:
        return data.decode('utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-16-le')
    return data.decode('utf-8-sig')


def windows(request):
    script = subprocess.check_output(['wslpath', '-w', str(SCRIPT.with_name('windows.ps1'))], text=True).strip() if os.name != 'nt' else str(SCRIPT.with_name('windows.ps1'))
    request = dict(request)
    timeout = request.get('timeout', 30)
    encoded = base64.b64encode(json.dumps(request, ensure_ascii=False).encode()).decode()
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-RequestBase64', encoded]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout + 10)
        if result.returncode:
            return dict(state='unknown', error='windows_collector_failed', detail=decode(result.stderr)[-1000:])
        return json.loads(decode(result.stdout))
    except subprocess.TimeoutExpired:
        if request.get('result_path'):
            path = request['result_path']
            if os.name != 'nt':
                path = subprocess.check_output(['wslpath', '-u', path], text=True).strip()
            try:
                partial = read(path); partial.update(state='partial', error='target_timeout', logical_bytes=None, allocated_bytes=None)
                return partial
            except (OSError, ValueError):
                pass
        return dict(state='unknown', error='target_timeout', logical_bytes=None, allocated_bytes=None)


def linux_scan(path, timeout):
    native_linux(path)
    started = time.monotonic(); sizes = {}; issues = []; state = 'complete'
    for field, extra in [('allocated_bytes', []), ('logical_bytes', ['--apparent-size'])]:
        command = ['du', '-x', '-P', '-B1', '--max-depth=1', *extra, '--', path]
        try:
            result = subprocess.run(command, capture_output=True, timeout=max(0.01, timeout - (time.monotonic() - started)), env=dict(os.environ, LC_ALL='C'))
            output = result.stdout.decode('utf-8', errors='replace')
            if result.returncode:
                state = 'partial'; issues.append('du_access_or_io_error')
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or b'').decode('utf-8', errors='replace'); state = 'partial'; issues.append('timeout')
        values = []
        for line in output.splitlines():
            number, sep, name = line.partition('\t')
            if sep and number.isdigit():
                values.append((name, int(number)))
        total = next((n for p, n in values if p.rstrip('/') == path.rstrip('/')), None)
        sizes[field] = total if state == 'complete' else None
        sizes['observed_' + field] = total if total is not None else (sum(n for _, n in values) if values else None)
    if state != 'complete':
        sizes['logical_bytes'] = sizes['allocated_bytes'] = None
    return dict(state=state, issues=issues, method='gnu-du-x', **sizes)


def linux_volume():
    try:
        result = subprocess.run(['df', '-B1', '--output=size,used,avail', '/'], capture_output=True, text=True, timeout=5, env=dict(os.environ, LC_ALL='C'), check=True)
        total, used, available = map(int, result.stdout.splitlines()[-1].split())
        swaps = []
        for line in Path('/proc/swaps').read_text().splitlines()[1:]:
            fields = line.split(); swaps.append(dict(path=fields[0], size_bytes=int(fields[2])*1024, used_bytes=int(fields[3])*1024, active=True))
        return dict(path='/', platform='linux', state='complete', total_bytes=total, used_bytes=used, free_bytes=available, swap=swaps)
    except (OSError, ValueError, subprocess.SubprocessError):
        return dict(path='/', platform='linux', state='unknown', free_bytes=None)


def config(path):
    data = read(path) if path else {}
    if not isinstance(data, dict) or data.get('version', 1) != 1:
        raise ValueError('Unsupported configuration')
    data.setdefault('timeout_seconds', 30)
    if not isinstance(data['timeout_seconds'], int) or not 1 <= data['timeout_seconds'] <= 600:
        raise ValueError('Target timeout must be 1..600 seconds')
    data.setdefault('preserve', []); data.setdefault('cleanup_roots', []); data.setdefault('candidates', [])
    data.setdefault('retention', dict(min_age_days=14, keep_latest=2, keep_rollback=1))
    for key in ('min_age_days', 'keep_latest', 'keep_rollback'):
        if not isinstance(data['retention'].get(key), int) or data['retention'][key] < 0:
            raise ValueError('Retention values must be nonnegative integers')
    for entry in data.get('targets', []) + data['cleanup_roots'] + data['candidates'] + data['preserve']:
        if entry.get('platform') not in ('linux', 'windows'):
            raise ValueError('Explicit linux/windows platform required')
        canonical(entry['path'], entry['platform'])
        if entry.get('process_probe','local') not in ('local','wsl-root'):raise ValueError('Unsupported process probe')
        if entry.get('symlink_policy','reject') not in ('reject','yarn-v6-bin'):raise ValueError('Unsupported symlink policy')
        if entry.get('symlink_policy')=='yarn-v6-bin' and (entry['platform']!='linux' or entry.get('classification')!='cache'):raise ValueError('Yarn link policy is for Linux cache candidates only')
    return data


def discovery():
    try:
        return windows(dict(mode='discover', timeout=15))
    except (OSError, ValueError, subprocess.SubprocessError):
        return dict(state='unknown', error='windows_unavailable', targets=[], volumes=[])


def measure(entry, timeout, mode='scan', win=None):
    platform = entry['platform']; path = canonical(entry['path'], platform)
    try:
        if platform == 'windows':
            result_path = None
            if win and win.get('temp'):
                result_path = win['temp'].rstrip('\\') + '\\storage-audit-' + uuid.uuid4().hex + '.json'
            result = windows(dict(mode=mode, path=path, timeout=timeout, result_path=result_path))
            result['method'] = 'win32-file-id-and-compressed-size'
            return result
        return linux_scan(path, timeout) if mode == 'scan' else inspect_linux(path, timeout, entry.get('symlink_policy','reject'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return dict(state='unknown', error=str(error), logical_bytes=None, allocated_bytes=None)


def scan(cfg, state):
    win = discovery()
    targets = cfg.get('targets')
    if targets is None:
        targets = [dict(platform='linux', path=str(p), kind='directory') for p in (Path.home()/'.cache', Path.home()/'.npm', Path('/tmp'))]
        targets += win.get('targets', [])
    snapshot = dict(version=1, measured_at=now(), volumes=[linux_volume(), *[dict(v, platform='windows') for v in win.get('volumes', [])]],
                    windows_discovery_state=win.get('state','complete'), targets=[], totals=None,
                    aggregation='nonadditive: nested paths, cross-target hardlinks and VHD/internal/swap layers must not be summed')
    seen = set()
    output = state / ('snapshot-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
    for index, entry in enumerate(targets):
        path = canonical(entry['path'], entry['platform']); key = (entry['platform'], path)
        if key in seen:
            continue
        seen.add(key)
        print(f'[{index+1}/{len(targets)}] {entry["platform"]}: {path}', file=sys.stderr, flush=True)
        result = measure(entry, cfg['timeout_seconds'], win=win)
        snapshot['targets'].append(dict(entry, **result))
        save(output, snapshot)
        print('  ' + result['state'], file=sys.stderr, flush=True)
    snapshot['completed_at'] = now(); save(output, snapshot)
    return dict(snapshot=str(output), state='complete' if all(t['state']=='complete' for t in snapshot['targets']) else 'partial', alerts=alerts(snapshot,cfg))


def alerts(snapshot, cfg, prior=None):
    result = []; low = cfg.get('low_free_gib', 20)*1024**3; growth = cfg.get('growth_gib', 5)*1024**3
    for volume in snapshot.get('volumes', []):
        if volume.get('free_bytes') is None:
            result.append(dict(kind='unknown_free_space', path=volume['path']))
        elif volume['free_bytes'] < low:
            result.append(dict(kind='low_free_space',path=volume['path'],free_bytes=volume['free_bytes']))
    if prior:
        old = {(t['platform'],canonical(t['path'],t['platform'])):t for t in prior.get('targets',[])}
        for t in snapshot['targets']:
            previous = old.get((t['platform'],canonical(t['path'],t['platform'])))
            if previous and all(x.get('state')=='complete' and x.get('allocated_bytes') is not None for x in (t,previous)) and t.get('method')==previous.get('method'):
                delta=t['allocated_bytes']-previous['allocated_bytes']
                if delta>=growth:result.append(dict(kind='rapid_growth',path=t['path'],delta_bytes=delta))
            else:
                result.append(dict(kind='unknown_comparison',path=t['path']))
    return result


def compare(state, period, cfg, current=None, previous=None):
    snapshots = [read(p) for p in state.glob('snapshot-*.json')]
    if current: latest=read(current)
    elif snapshots: latest=max(snapshots,key=lambda s:s['measured_at'])
    else: return dict(state='unknown',reason='no_snapshots')
    boundary=datetime.fromisoformat(latest['measured_at'])-timedelta(days=1 if period=='day' else 7)
    eligible=[s for s in snapshots if datetime.fromisoformat(s['measured_at'])<=boundary]
    prior=read(previous) if previous else (max(eligible,key=lambda s:s['measured_at']) if eligible else None)
    if not prior:return dict(state='unknown',reason='no_prior_period_snapshot',alerts=alerts(latest,cfg))
    return dict(state='compared',period=period,current=latest['measured_at'],previous=prior['measured_at'],alerts=alerts(latest,cfg,prior))


def preserve_guard(item, cfg):
    for keep in cfg.get('preserve', []):
        if keep['platform'] != item['platform']:
            continue
        # Never remove an ancestor containing preserved data. root_only allows
        # individually verified disposable descendants, never the shared root.
        ancestor = inside(keep['path'], item['path'], item['platform'])
        descendant = inside(item['path'], keep['path'], item['platform'])
        if ancestor or (descendant and not keep.get('root_only', False)):
            raise ValueError('explicit_preserve_path')


def activity(item, timeout):
    try:
        if item['platform'] == 'linux':
            scope=item.get('process_probe_scope',item['path'])
            if not inside(item['path'],scope,'linux'):raise ValueError('Process probe scope does not contain candidate')
            return activity_linux(scope, timeout, backend=item.get('process_probe','local'))
        return windows(dict(mode='activity', path=item['path'], timeout=timeout))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return dict(state='unknown', reason=str(e), handles='unknown')


def free_space():
    win = discovery()
    return dict(measured_at=now(), linux_internal=linux_volume(),
                windows_host=win.get('volumes', []), windows_state=win.get('state', 'complete'))


def plan(cfg):
    win = discovery() if any(c['platform']=='windows' for c in cfg['candidates']) else {}
    items=[];seen=set();runtime_cache={}
    for index,c in enumerate(cfg['candidates']):
        key=(c['platform'],canonical(c['path'],c['platform']))
        if key in seen:raise ValueError('Duplicate candidate path')
        seen.add(key)
        item=dict(c,path=key[1],reasons=[])
        print(f'[{index+1}/{len(cfg["candidates"])}] inspect {item["path"]}',file=sys.stderr,flush=True)
        try:
            preserve_guard(c,cfg)
            policy_guard(c,cfg['cleanup_roots'])
            item['measurement']=measure(c,cfg['timeout_seconds'],mode='inspect',win=win)
            m=item['measurement']
            if m['state']!='complete':item['reasons'].append('incomplete_measurement')
            if m.get('hardlinks'):item['reasons'].append('hardlinks')
            if time.time()-m.get('modified_epoch',time.time()) < cfg['retention']['min_age_days']*86400:item['reasons'].append('retention_age')
        except (OSError,ValueError,subprocess.SubprocessError) as e:
            item['reasons'].append(str(e)); item['measurement']=dict(state='unknown',logical_bytes=None,allocated_bytes=None)
        if c.get('owner_verified') is not True or not c.get('provenance'):item['reasons'].append('owner_not_verified')
        if not c.get('recreation_cost'):item['reasons'].append('recreation_cost_unknown')
        if not isinstance(c.get('requires_app_exit'),bool):item['reasons'].append('app_exit_requirement_unknown')
        if c.get('regenerable_verified') is not True:item['reasons'].append('regeneration_not_verified')
        if c.get('classification') == 'agent_temp' and c.get('owner_task_completed') is not True:item['reasons'].append('owner_task_not_completed')
        runtime_key=(c['platform'],c.get('process_probe','local'),c.get('process_probe_scope',c['path']))
        if c.get('process_probe_scope') and not inside(c['path'],c['process_probe_scope'],c['platform']):
            item['activity']=dict(state='unknown',reason='probe_scope_mismatch',handles='unknown')
        elif item['measurement'].get('state')=='complete':
            if runtime_key not in runtime_cache:runtime_cache[runtime_key]=activity(c,cfg['timeout_seconds'])
            item['activity']=runtime_cache[runtime_key]
        else:item['activity']=dict(state='unknown',handles='unknown',reason='manifest_incomplete')
        if item['activity'].get('state')!='inactive':item['reasons'].append('runtime_'+item['activity'].get('state','unknown'))
        if c.get('current') is True:item['reasons'].append('current_version')
        if c.get('classification') in ('unused_version','old_build') and not c.get('group'):item['reasons'].append('version_group_unknown')
        items.append(item)
    # The current and rollback flags are explicit inventory facts, not guessed from names.
    groups={c.get('group') for c in items if c.get('group')}
    for group in groups:
        members=sorted([c for c in items if c.get('group')==group],key=lambda c:c['measurement'].get('modified_epoch',float('inf')),reverse=True)
        # Unknown timestamps are held without consuming the slots protecting
        # the newest known releases.
        ordinary=[c for c in members if not c.get('rollback') and c['measurement'].get('modified_epoch') is not None]
        rollback=[c for c in members if c.get('rollback') and c['measurement'].get('modified_epoch') is not None]
        for c in ordinary[:cfg['retention']['keep_latest']]+rollback[:cfg['retention']['keep_rollback']]:c['reasons'].append('retained_recent_or_rollback')
    # Paths are canonical and duplicates rejected above. Walk ancestors once
    # instead of comparing every pair in large package-cache inventories.
    by_path={(c['platform'],c['path']):index for index,c in enumerate(items)}
    overlapping=set()
    for index,c in enumerate(items):
        cls=PureWindowsPath if c['platform']=='windows' else Path
        for parent in cls(c['path']).parents:
            other=by_path.get((c['platform'],str(parent)))
            if other is not None:overlapping.update((index,other))
    for index,c in enumerate(items):
        if index in overlapping:c['reasons'].append('overlapping_candidates')
        c['eligible']=not c['reasons']
    result=dict(version=2,created_at=now(),expires_at=datetime.fromtimestamp(time.time()+86400,timezone.utc).isoformat(),
                config=cfg,items=items,total_reclaimable_bytes=None,approval_required=True)
    result['digest']=digest(result);return result


def apply(plan_data, approval=None, execute=False):
    if plan_data.get('version') != 2:raise ValueError('Plan version changed; inspect again with runtime and preservation checks')
    contents={k:v for k,v in plan_data.items() if k!='digest'}
    if digest(contents)!=plan_data.get('digest'):raise ValueError('Plan digest mismatch')
    if datetime.fromisoformat(plan_data['expires_at'])<datetime.now(timezone.utc):raise ValueError('Plan expired; inspect again')
    if not approval:
        if execute:raise ValueError('Explicit exact-path approval required')
        return dict(state='dry_run',items=plan_data['items'],deleted=0)
    if approval.get('plan_digest')!=plan_data['digest'] or approval.get('approved') is not True:raise ValueError('Approval does not match this plan')
    selected=approval.get('items',[])
    if not selected:raise ValueError('Approval allowlist is empty')
    cfg=config_from_plan(plan_data); known={(i['platform'],i['path']):i for i in plan_data['items']}
    checked=[];keys=set()
    for entry in selected:
        key=(entry['platform'],canonical(entry['path'],entry['platform']))
        if key in keys:raise ValueError('Duplicate approval item')
        keys.add(key);item=known.get(key)
        if not item or not item['eligible']:raise ValueError('Unapproved or ineligible exact path')
        if entry.get('inactive_confirmed') is not True:raise ValueError('Active use is unknown; refuse cleanup')
        if entry.get('fingerprint')!=item['measurement']['fingerprint'] or entry.get('logical_bytes')!=item['measurement']['logical_bytes']:raise ValueError('Approval size or fingerprint mismatch')
        if item['requires_app_exit'] and entry.get('app_exit_confirmed') is not True:raise ValueError('Required app exit is not confirmed')
        preserve_guard(item,cfg)
        policy_guard(item,cfg['cleanup_roots'])
        actual=measure(item,cfg['timeout_seconds'],mode='inspect')
        if actual.get('state')!='complete' or actual.get('fingerprint')!=entry['fingerprint'] or actual.get('logical_bytes')!=entry['logical_bytes'] or actual.get('hardlinks'):raise ValueError('Candidate changed; create a new plan')
        checked.append(item)
    if not execute:return dict(state='dry_run',paths=[i['path'] for i in checked],deleted=0)
    results=[]; before=free_space()
    for item in checked:
        try:
            preserve_guard(item,cfg)
            runtime=activity(item,cfg['timeout_seconds'])
            if runtime.get('state')!='inactive':
                results.append(dict(path=item['path'],state='skipped',activity=runtime));continue
            if item['platform']=='linux':
                policy_guard(item,cfg['cleanup_roots']);delete_linux(item['path'],item['measurement'],cfg['timeout_seconds'],item.get('symlink_policy','reject'),item.get('process_probe','local'));result=dict(state='deleted')
            else:
                result=windows(dict(mode='apply',path=item['path'],timeout=cfg['timeout_seconds'],confirmed=True,**{k:item['measurement'][k] for k in ('fingerprint','logical_bytes')}))
            results.append(dict(path=item['path'],**result))
            if result['state']!='deleted':break
        except (OSError,ValueError,subprocess.SubprocessError) as e:
            results.append(dict(path=item['path'],state='refused_or_partial',error=str(e)));break
    return dict(state='complete' if len(results)==len(checked) and all(r['state']=='deleted' for r in results) else 'partial',
                space_before=before,space_after=free_space(),space_note='Observed free bytes by layer; concurrent writes affect deltas. Linux unlink is not Windows host reclaim.',
                results=results,not_attempted=[i['path'] for i in checked[len(results):]])


def config_from_plan(data):
    # Validate embedded configuration using the same checks without accepting a replacement file.
    cfg=data['config']
    if cfg.get('version',1)!=1 or not 1<=cfg['timeout_seconds']<=600:raise ValueError('Invalid embedded configuration')
    return cfg


def main():
    parser=argparse.ArgumentParser(description='Read-only audit first; exact-path approval required for cleanup')
    parser.add_argument('--state',type=Path,default=DEFAULT_STATE)
    sub=parser.add_subparsers(dest='mode',required=True)
    for mode in ('scan','plan','compare','schedule-plan'):
        p=sub.add_parser(mode);p.add_argument('--config',type=Path)
        if mode=='plan':p.add_argument('--output',type=Path,required=True)
        if mode=='compare':p.add_argument('--period',choices=['day','week'],default='day');p.add_argument('--current');p.add_argument('--previous')
        if mode=='schedule-plan':p.add_argument('--period',choices=['day','week'],default='day')
    p=sub.add_parser('apply');p.add_argument('--plan',type=Path,required=True);p.add_argument('--approval',type=Path);p.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:
        if args.mode=='apply':
            result=apply(read(args.plan),read(args.approval) if args.approval else None,args.execute)
            save(args.state/('apply-'+uuid.uuid4().hex+'.json'),result)
        else:
            cfg=config(args.config)
            if args.mode=='scan':result=scan(cfg,args.state)
            elif args.mode=='plan':result=plan(cfg);save(args.output,result);result=dict(plan=str(args.output),digest=result['digest'],items=result['items'])
            elif args.mode=='compare':result=compare(args.state,args.period,cfg,args.current,args.previous)
            else:result=dict(state='proposal_only',period=args.period,approval_required=True,command=[sys.executable,str(SCRIPT),'--state',str(args.state),'scan',*(['--config',str(args.config.resolve())] if args.config else [])],enabled=False)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result.get('state') in ('partial','refused_or_partial') and args.mode=='apply' else 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as e:
        print(json.dumps(dict(state='refused',error=str(e)),ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
