#!/usr/bin/env python3
"""Exercise production orchestration with an injected, non-mutating command adapter."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'linux'))
from runner import execute
from lib.config import defaults, validate

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    config = validate(defaults())
    for label, failures in [('success', {}), ('KB auth', {'kb':20}), ('base failure', {'base':1}), ('Node failure', {'node':1}), ('Orca unavailable', {'orca':20})]:
        calls=[]; installed=set()
        def command(item, mode):
            calls.append((item,mode))
            if mode=='check': return 0 if item in installed else 1
            if item in failures: return failures[item]
            installed.add(item); return 0
        file=root/(label+'.jsonl')
        result=execute(config,file,executor=command)
        events=[json.loads(line) for line in file.read_text().splitlines()]
        states={e['step']:e['status'] for e in events}
        assert result == (1 if failures else 0), events
        assert states['orca-patch']=='skipped'
        assert states['orca-monitor']=='skipped'
        assert states['orca-auto']=='skipped'
        assert states['shell-replace']=='skipped'
        if 'base' in failures:
            assert not any(mode=='apply' and item!='base' for item,mode in calls)
        if 'node' in failures:
            assert ('claude','apply') not in calls
            assert ('gh','apply') in calls and ('orca','apply') in calls
        if 'kb' in failures:
            assert states['kb']=='action-required' and states['orca']=='completed'
        print('PASS:',label)
    file=root/'resume.jsonl'
    calls=[]
    assert execute(config,file,executor=lambda item,mode: calls.append((item,mode)) or 0)==0
    assert all(mode=='check' for _,mode in calls)
    print('PASS: resume verifies actual state without reapplying')
    file=root/'stop.jsonl';file.with_suffix('.stop').write_text('stop')
    assert execute(config,file,executor=lambda *_: (_ for _ in ()).throw(AssertionError('unexpected command')))==2
    print('PASS: stop at step boundary')
    file=root/'retry.jsonl'; calls=[]
    assert execute(config,file,step='kb',executor=lambda item,mode:calls.append((item,mode)) or 0)==0
    assert all(mode=='check' for _,mode in calls)
    print('PASS: single-step retry rechecks dependencies')

    monitor = validate({**defaults(), 'selected': ['base', 'orca-monitor']})
    file = root/'monitor.jsonl'; calls=[]; installed=set()
    def monitor_command(item, mode):
        calls.append((item, mode))
        if mode == 'check': return 0 if item in installed else 1
        installed.add(item); return 0
    assert execute(monitor, file, executor=monitor_command) == 0
    assert ('orca-monitor', 'apply') in calls
    assert not any(item in ('orca', 'orca-patch') for item, _ in calls)
    assert calls.index(('base', 'apply')) < calls.index(('orca-monitor', 'apply'))
    print('PASS: opt-in monitor installs independently of Orca skills and patch')

    auto = validate({**defaults(), 'selected': ['base', 'orca-auto']})
    calls.clear(); installed.clear()
    assert execute(auto, root/'auto.jsonl', executor=monitor_command) == 0
    assert ('orca-auto', 'apply') in calls
    assert not any(item in ('node', 'orca', 'orca-patch', 'orca-monitor') for item, _ in calls)
    assert calls.index(('base', 'apply')) < calls.index(('orca-auto', 'apply'))
    print('PASS: auto-patch installs without external Node or Orca skill prerequisites')
