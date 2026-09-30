#!/usr/bin/env python3
"""Local multi-device usage pipeline; no LLM, paid API, or source-log upload."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import uuid

from usage_store import SCHEMA, METRICS, aggregate, atomic, digest, lock, now, publish, read, scan
import usage_render

DEFAULT = Path.home() / '.config/ai-workflow/tracking.json'
SCRIPT = Path(__file__).resolve()


def git(path, *args, input=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    return subprocess.run(['git', '-C', str(path), *args], input=input, capture_output=True, text=True, check=True, timeout=90, env=env).stdout.strip()

def require_id(value):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}', value):
        raise ValueError('identifier must contain only letters, digits, dots, underscores and hyphens')
    return value

def initialize(args):
    config_path = Path(args.config).expanduser().resolve()
    if config_path.exists():
        raise ValueError('configuration exists; refusing to overwrite device identity')
    repo = Path(args.repo).expanduser().resolve()
    target = Path(args.worktree).expanduser().resolve()
    if target == repo or target.exists():
        raise ValueError('use a new dedicated worktree directory')
    branch = 'usage-data'
    git(repo, 'remote', 'get-url', 'origin')
    refs = git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/usage-data', 'refs/remotes/origin/usage-data').splitlines()
    # Discover a remote branch before creating the first local branch. Offline setup
    # must be retried rather than accidentally creating unrelated device histories.
    git(repo, 'fetch', 'origin')
    refs = git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/usage-data', 'refs/remotes/origin/usage-data').splitlines()
    if 'refs/heads/usage-data' in refs:
        git(repo, 'worktree', 'add', str(target), branch)
    elif 'refs/remotes/origin/usage-data' in refs:
        git(repo, 'worktree', 'add', '-b', branch, str(target), 'origin/usage-data')
    else:
        tree = git(repo, 'hash-object', '-w', '-t', 'tree', '--stdin', input='')
        commit = git(repo, 'commit-tree', tree, '-m', 'Initialize isolated usage data history')
        git(repo, 'worktree', 'add', '-b', branch, str(target), commit)
    device = require_id(args.device or ('device-' + uuid.uuid4().hex[:12]))
    if (target / 'devices' / device).exists():
        raise ValueError('device identity already exists; choose a new device ID')
    state = Path(args.state).expanduser().resolve()
    source_config = read(Path.home() / '.config/ai-workflow/usage.json', {})
    roots = []
    for home in source_config.get('homes', [str(Path.home())]):
        for tool, relative in [('Codex', '.codex/sessions'), ('Codex', '.codex/archived_sessions'), ('Claude', '.claude/projects')]:
            path = Path(home) / relative
            if Path(home) == Path.home():
                if tool == 'Codex' and os.environ.get('CODEX_HOME'):
                    path = Path(os.environ['CODEX_HOME']) / Path(relative).name
                elif tool == 'Claude' and os.environ.get('CLAUDE_CONFIG_DIR'):
                    path = Path(os.environ['CLAUDE_CONFIG_DIR']) / 'projects'
            roots.append(dict(tool=tool, path=str(path), required=path.is_dir()))
    config = dict(schema=SCHEMA, device=device, repo=str(repo), worktree=str(target), state=str(state), roots=roots, projects={},
                  template=str(repo / 'templates/usage-report.html'), reports=str(repo / 'archive/reports/usage/generated'),
                  improvements=str(repo / 'archive/reports/usage/improvements.json'), timezone='Asia/Seoul', branch=branch, remote_fingerprint=digest(git(repo, 'remote', 'get-url', 'origin')))
    atomic(config_path, config)
    atomic(target / 'devices' / device / 'registration.json', dict(schema=SCHEMA, device=device, registered_at=now().isoformat(), platform=platform.system(), tools=['Codex', 'Claude']))
    return dict(config=str(config_path), device=device, state='prepared_not_enabled')

def guard(config):
    target = Path(config['worktree']).resolve()
    if target == Path(config['repo']).resolve():
        raise ValueError('automation cannot use the ordinary working directory')
    if Path(git(target, 'rev-parse', '--show-toplevel')).resolve() != target:
        raise ValueError('incorrect worktree root')
    if git(target, 'branch', '--show-current') != 'usage-data':
        raise ValueError('wrong branch')
    common = Path(git(target, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()
    ordinary = Path(git(config['repo'], 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()
    if common != ordinary:
        raise ValueError('worktree does not belong to configured repository')
    if git(target, 'ls-files', '-u'):
        raise ValueError('unmerged files; manual resolution required')
    if config.get('remote_fingerprint') and digest(git(target, 'remote', 'get-url', 'origin')) != config['remote_fingerprint']:
        raise ValueError('configured remote changed; synchronization held')
    own = f"devices/{require_id(config['device'])}/"
    changed = git(target, 'diff', '--name-only', '-z', 'HEAD').split('\0')
    untracked = git(target, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
    staged = git(target, 'diff', '--cached', '--name-only', '-z').split('\0')
    for path in changed + untracked + staged:
        if path and (not path.startswith(own) or not path.endswith('.json')):
            raise ValueError('unexpected modified file in automation worktree')
    for path in (target / own).rglob('*'):
        if path.is_symlink():
            raise ValueError('symlinks forbidden in published data')
    return target

def sync(config):
    target = guard(config)
    own = f"devices/{config['device']}"
    git(target, 'add', '--', own)
    if git(target, 'diff', '--cached', '--name-only'):
        git(target, '-c', 'core.hooksPath=/dev/null' if os.name != 'nt' else 'core.hooksPath=NUL', 'commit', '-m', f"usage: update {config['device']}")
    for attempt in range(3):
        git(target, 'fetch', 'origin')
        if git(target, 'for-each-ref', '--format=%(refname)', 'refs/remotes/origin/usage-data'):
            remote_changes = git(target, 'diff', '--name-only', 'HEAD...origin/usage-data').splitlines()
            local_changes = git(target, 'diff', '--name-only', 'origin/usage-data...HEAD').splitlines()
            if set(remote_changes) & set(local_changes):
                raise ValueError('concurrent edits to the same device data; synchronization held')
            try:
                git(target, '-c', 'core.hooksPath=/dev/null' if os.name != 'nt' else 'core.hooksPath=NUL', 'merge', '--no-edit', 'origin/usage-data')
            except subprocess.CalledProcessError:
                git(target, 'merge', '--abort')
                raise
        try:
            git(target, 'push', 'origin', 'HEAD:refs/heads/usage-data')
            return dict(state='ok', last_attempt=now().isoformat(), last_success=now().isoformat(), attempts=attempt + 1)
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
    raise RuntimeError('sync retries exhausted')

def approval(config):
    return Path(config['repo']) / 'archive/reports/usage/template-approval.json'

def is_approved(config):
    return read(approval(config), {}).get('fingerprint') == usage_render.fingerprint(config['template'])

def make_report(config, preview=False, year=None):
    year = year or now().astimezone(__import__('usage_store').TZ).year
    report = aggregate(config['worktree'], year)
    report['weeks'] = [w for w in report['weeks'] if w['week'].startswith(str(year))]
    from usage_store import FIELDS
    report['totals'] = {k: sum(w['totals'][k] for w in report['weeks']) for k in (*FIELDS, 'responses', 'total', 'non_cache_read_input')}
    directory = Path(config['reports'])
    report['year'] = year
    report['last_sync'] = read(Path(config['state']) / 'sync.json', {})
    atomic(directory / f'{year}.json', report)
    output = directory / (f'{year}-preview.html' if preview else f'{year}.html')
    usage_render.render(report, config['template'], output, approval(config), preview,
                        read(config['improvements'], []))
    if preview:
        atomic(Path(config['state']) / 'preview.json', dict(fingerprint=usage_render.fingerprint(config['template']), path=str(output), created=now().isoformat()))
    return str(output)

def run(config, do_sync=False):
    guard(config)
    state = Path(config['state'])
    status = read(state / 'run.json', {})
    status.pop('sync_error', None)
    status.update(last_attempt=now().isoformat(), state='running')
    atomic(state / 'run.json', status)
    try:
        snapshot, quality = scan(config)
        quality['last_sync'] = read(state / 'sync.json', {})
        publish(config, snapshot, quality)
        total_bytes = sum(p.stat().st_size for p in Path(config['worktree']).rglob('*.json'))
        status.update(last_collection=quality, data_bytes=total_bytes,
                      git_objects=git(config['worktree'], 'count-objects', '-v'))
        storage = dict(timestamp=now().isoformat(), data_bytes=total_bytes, git_objects=status['git_objects'])
        atomic(Path(config['worktree']) / 'devices' / config['device'] / 'storage' / (now().strftime('%Y-%m-%d') + '.json'), storage)
        if do_sync:
            try:
                result = sync(config)
                atomic(state / 'sync.json', result)
                status['last_sync'] = result
            except (subprocess.SubprocessError, ValueError) as error:
                status['sync_error'] = type(error).__name__
                previous = read(state / 'sync.json', {})
                atomic(state / 'sync.json', dict(previous, state='failed', last_attempt=now().isoformat(), error_type=type(error).__name__))
        report_path = None
        # Daily generation also catches a missed Monday. Fixed local renderer only.
        if is_approved(config):
            status['html'] = 'approved'
            report_path = make_report(config)
        else:
            report = aggregate(config['worktree'])
            atomic(Path(config['reports']) / 'latest.json', report)
            status['html'] = 'pending_approval'
        status.update(state='attention' if quality['issues'] or status.get('sync_error') else 'ok', report=report_path)
        if status['state'] == 'ok':
            status['last_success'] = now().isoformat()
        return status
    except Exception as error:
        status.update(state='failed', error_type=type(error).__name__)
        raise
    finally:
        atomic(state / 'run.json', status)
        month = now().strftime('%Y-%m')
        atomic(state / 'storage' / (month + '.json'), dict(timestamp=now().isoformat(), data_bytes=status.get('data_bytes'), git_objects=status.get('git_objects')))

def record_task(config, source):
    data = read(source)
    allowed = {'id', 'project', 'type', 'status', 'sessions', 'verification', 'rework', 'rework_reason', 'parent_task', 'improvements', 'kb_documents', 'evidence_kind', 'since', 'until'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('unexpected task fields; do not store raw logs')
    require_id(data['id'])
    if not isinstance(data.get('project'), str) or not re.fullmatch(r'[a-zA-Z0-9_./-]{1,120}', data['project']) or '..' in data['project']:
        raise ValueError('use a canonical project identifier')
    from usage_report import stamp
    for field in ('since', 'until'):
        if data.get(field) and stamp(data[field]) is None:
            raise ValueError('invalid task time boundary')
    if data.get('since') and data.get('until') and stamp(data['since']) >= stamp(data['until']):
        raise ValueError('task interval must be positive')
    if len(json.dumps(data, ensure_ascii=False)) > 8000:
        raise ValueError('task metadata too large; keep evidence concise')
    if data.get('rework') is not None and not isinstance(data.get('rework'), bool):
        raise ValueError('rework must be true, false or null')
    checks = data.get('verification')
    if checks is not None and (not isinstance(checks, list) or any(not isinstance(c, dict) or set(c) != {'name','result'} or c['result'] not in ('pass','fail','not_run','unknown') for c in checks)):
        raise ValueError('verification must list {name, result: pass|fail|not_run|unknown}')
    # The blog ingest rejects the whole export when a published task text exceeds 300 characters.
    if any(isinstance(v, str) and len(v) > 300 for v in [data.get('type')] + [c['name'] for c in checks or []]):
        raise ValueError('task type and verification names must be 300 characters or fewer')
    if data['status'] not in ('completed', 'partial', 'in_progress', 'stopped'):
        raise ValueError('invalid task status')
    if not isinstance(data.get('sessions'), list) or any(not re.fullmatch('[0-9a-f]{64}', s) for s in data['sessions']):
        raise ValueError('use session keys from the collected data')
    for field in ('project', 'type', 'verification', 'rework', 'rework_reason', 'parent_task', 'improvements', 'kb_documents'):
        data.setdefault(field, None)
    data.setdefault('evidence_kind', 'explicit_record')
    if data['evidence_kind'] not in ('explicit_record', 'observed'):
        raise ValueError('inferred task results are not accepted')
    path = guard(config) / 'devices' / config['device'] / 'tasks' / (digest([data['project'], data['id']]) + '.json')
    atomic(path, data)
    return str(path)

def scheduler(config, config_path, enable=False):
    if enable and not is_approved(config):
        raise ValueError('approve the concrete HTML preview before enabling scheduled operation')
    args = [sys.executable, str(SCRIPT), '--config', str(Path(config_path).resolve()), 'scheduled']
    system = platform.system()
    state = Path(config['state']) / 'scheduler'
    state.mkdir(parents=True, exist_ok=True)
    if system == 'Linux':
        def quote(s):
            return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
        service = '[Unit]\nDescription=Local AI usage collection and synchronization\n\n[Service]\nType=oneshot\nExecStart=' + ' '.join(map(quote, args)) + '\nTimeoutStartSec=20min\nUMask=0077\n'
        timer = '[Unit]\nDescription=Daily AI usage collection (Asia/Seoul)\n\n[Timer]\nOnCalendar=*-*-* 09:00:00 Asia/Seoul\nOnStartupSec=3min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n'
        (state / 'ai-usage.service').write_text(service)
        (state / 'ai-usage.timer').write_text(timer)
        if enable:
            import shutil
            dest = Path.home() / '.config/systemd/user'; dest.mkdir(parents=True, exist_ok=True)
            for name in ('ai-usage.service', 'ai-usage.timer'):
                target = dest / name
                if target.exists() and target.read_bytes() != (state / name).read_bytes():
                    raise ValueError('existing different scheduler unit; refusing overwrite')
                shutil.copyfile(state / name, target)
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'ai-usage.timer'], check=True)
    elif system == 'Darwin':
        import plistlib
        # launchd calendar is local time; the runner's data boundaries remain KST.
        value = dict(Label='local.ai-usage', ProgramArguments=args, RunAtLoad=True, StartInterval=900,
                     StandardOutPath=str(state / 'stdout.log'), StandardErrorPath=str(state / 'stderr.log'))
        path = state / 'local.ai-usage.plist'; path.write_bytes(plistlib.dumps(value))
        if enable:
            import shutil
            dest = Path.home() / 'Library/LaunchAgents/local.ai-usage.plist'; dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.read_bytes() != path.read_bytes():
                raise ValueError('existing different launch agent')
            shutil.copyfile(path, dest)
            subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(dest)], check=True)
    elif system == 'Windows':
        import xml.etree.ElementTree as ET
        root = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
        triggers = ET.SubElement(root, 'Triggers')
        daily = ET.SubElement(triggers, 'CalendarTrigger')
        ET.SubElement(daily, 'StartBoundary').text = '2026-01-01T09:00:00+09:00'
        ET.SubElement(ET.SubElement(daily, 'ScheduleByDay'), 'DaysInterval').text = '1'
        ET.SubElement(triggers, 'LogonTrigger')
        settings = ET.SubElement(root, 'Settings'); ET.SubElement(settings, 'StartWhenAvailable').text = 'true'
        ET.SubElement(settings, 'MultipleInstancesPolicy').text = 'IgnoreNew'
        action = ET.SubElement(ET.SubElement(root, 'Actions'), 'Exec')
        ET.SubElement(action, 'Command').text = args[0]
        ET.SubElement(action, 'Arguments').text = subprocess.list2cmdline(args[1:])
        path = state / 'ai-usage.xml'; ET.ElementTree(root).write(path, encoding='utf-16', xml_declaration=True)
        if enable:
            subprocess.run(['schtasks', '/Create', '/TN', 'AI Usage Tracking', '/XML', str(path)], check=True)
    else:
        raise ValueError('unsupported scheduler platform')
    return dict(platform=system, files=str(state), enabled=enable)

def accept_correction(config, source, candidate_hash, reason):
    state = Path(config['state'])
    path = state / 'quarantine' / (source + '.json')
    candidate = read(path)
    if not candidate or digest(candidate) != candidate_hash:
        raise ValueError('correction fingerprint mismatch; inspect the current candidate')
    cache = read(state / 'source-cache.json')
    matches = [key for key in cache['files'] if digest(key) == source]
    if len(matches) != 1 or digest(cache['files'][matches[0]]['records']) != candidate['previous']:
        raise ValueError('source changed since correction was proposed')
    cache['files'][matches[0]] = {key: candidate[key] for key in ('records', 'events', 'fingerprint', 'metrics', 'parser')}
    event = dict(source=source, previous=candidate['previous'], accepted=digest(candidate['records']), reason=reason,
                 timestamp=now().isoformat(), candidate=candidate_hash)
    target = guard(config) / 'devices' / config['device'] / 'corrections' / (candidate_hash + '.json')
    atomic(target, event)
    atomic(state / 'source-cache.json', cache)
    path.unlink()
    return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT))
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--repo', required=True); init.add_argument('--device')
    init.add_argument('--worktree', default=str(Path.home() / '.local/share/usage-sync'))
    init.add_argument('--state', default=str(Path.home() / '.local/state/ai-workflow/tracking'))
    p = sub.add_parser('run'); p.add_argument('--sync', action='store_true')
    p = sub.add_parser('report'); p.add_argument('--preview', action='store_true'); p.add_argument('--year', type=int)
    p = sub.add_parser('approve'); p.add_argument('--fingerprint', required=True)
    sub.add_parser('status'); sub.add_parser('sync'); sub.add_parser('scheduled')
    p = sub.add_parser('kb-selection'); p.add_argument('--document', required=True); p.add_argument('--task', required=True)
    p = sub.add_parser('accept-correction'); p.add_argument('--source', required=True); p.add_argument('--candidate', required=True); p.add_argument('--reason', required=True, choices=['verified_source_correction', 'verified_source_replacement'])
    p = sub.add_parser('session-key'); p.add_argument('--tool', choices=['Codex','Claude'], required=True); p.add_argument('--id', required=True)
    p = sub.add_parser('schedule'); p.add_argument('--enable', action='store_true')
    p = sub.add_parser('task'); p.add_argument('--file', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args)
        else:
            config = read(args.config)
            if not config:
                raise ValueError('initialize the tracking configuration first')
            with lock(config['state']):
                if args.command == 'run':
                    result = run(config, args.sync)
                elif args.command == 'scheduled':
                    from usage_store import TZ
                    current = now().astimezone(TZ)
                    due = (current - timedelta(days=1) if current.hour < 9 else current).date().isoformat()
                    marker = Path(config['state']) / 'scheduled.json'
                    if read(marker, {}).get('completed_period') == due:
                        result = dict(state='already_collected', period=due)
                    else:
                        result = run(config, True)
                        if result['state'] == 'ok':
                            atomic(marker, dict(completed_period=due))
                elif args.command == 'kb-selection':
                    document = (Path(config['repo']) / args.document).resolve()
                    if not document.is_relative_to(Path(config['repo']).resolve()) or not document.is_file():
                        raise ValueError('select an existing KB document')
                    event = dict(key=uuid.uuid4().hex, kind='kb_selection', timestamp=now().isoformat(), document=document.relative_to(Path(config['repo'])).as_posix(), task=require_id(args.task), evidence_kind='explicit_record')
                    atomic(Path(config['state']) / 'kb-events' / (event['key'] + '.json'), event)
                    result = event
                elif args.command == 'report':
                    result = dict(path=make_report(config, args.preview, args.year), fingerprint=usage_render.fingerprint(config['template']))
                elif args.command == 'approve':
                    preview = read(Path(config['state']) / 'preview.json', {})
                    if args.fingerprint != preview.get('fingerprint') or args.fingerprint != usage_render.fingerprint(config['template']):
                        raise ValueError('approval must match the current generated preview fingerprint')
                    atomic(approval(config), dict(fingerprint=args.fingerprint, approved_at=now().isoformat(), preview=Path(preview['path']).name))
                    result = dict(approved=True)
                elif args.command == 'status':
                    result = dict(run=read(Path(config['state']) / 'run.json', {}), sync=read(Path(config['state']) / 'sync.json', {}), approved=is_approved(config))
                elif args.command == 'sync':
                    result = sync(config); atomic(Path(config['state']) / 'sync.json', result)
                elif args.command == 'session-key':
                    result = dict(session=digest([args.tool, args.id]))
                elif args.command == 'accept-correction':
                    if not re.fullmatch('[0-9a-f]{64}', args.source) or not re.fullmatch('[0-9a-f]{64}', args.candidate):
                        raise ValueError('invalid correction identifier')
                    result = accept_correction(config, args.source, args.candidate, args.reason)
                elif args.command == 'task':
                    result = dict(path=record_task(config, args.file))
                else:
                    result = scheduler(config, args.config, args.enable)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=type(error).__name__, message=str(error)), ensure_ascii=False), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
