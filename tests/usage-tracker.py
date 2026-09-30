#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/usage-report/scripts'
sys.path.insert(0, str(SCRIPTS))
import usage_store as store
import usage_tracker as tracker
import usage_render as render


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.logs = self.root / 'logs'; self.logs.mkdir()
        self.cfg = dict(device='test', state=str(self.root/'state'), worktree=str(self.root/'data'),
                        roots=[dict(tool='Codex', path=str(self.logs))], projects={'demo': 'muring/demo'})
        self.ts = store.now().isoformat()
    def tearDown(self):
        self.tmp.cleanup()
    def source(self, n=100, extra=None):
        rows = [dict(timestamp=self.ts, type='session_meta', payload=dict(id='s', cwd='/private/demo')),
                dict(timestamp=self.ts, type='turn_context', payload=dict(model='model', effort='medium')),
                dict(timestamp=self.ts, type='token_usage_record', payload=dict(response_id='r', usage=dict(input_tokens=n, cached_input_tokens=20, output_tokens=5)))]
        if extra: rows.extend(extra)
        path=self.logs/'s.jsonl'; path.write_text('\n'.join(map(json.dumps,rows)))
        return path
    def test_roundtrip_idempotency_privacy_effort(self):
        self.source(); snapshot, quality=store.scan(self.cfg)
        self.assertFalse(quality['issues']); self.assertEqual(snapshot['records'][0]['effort'], 'medium')
        self.assertNotIn('reasoning',snapshot['records'][0]['observed_fields'])
        self.assertIn('input',snapshot['records'][0]['observed_fields'])
        store.publish(self.cfg,snapshot,quality)
        report=store.aggregate(self.cfg['worktree'])
        self.assertEqual(report['totals']['input'],100)
        self.assertEqual(report['weeks'][-1]['task_states']['unclassified']['responses'],1)
        _, second=store.scan(self.cfg); self.assertEqual(second['files_parsed'],0)
        contents=''.join(p.read_text() for p in Path(self.cfg['worktree']).rglob('*.json'))
        self.assertNotIn('/private/',contents); self.assertNotIn('"r"',contents)
    def test_missing_and_regressed_logs_preserve_last_good(self):
        source=self.source(); s,q=store.scan(self.cfg); store.publish(self.cfg,s,q)
        previous=(Path(self.cfg['worktree'])/'devices/test/manifest.json').read_bytes()
        self.source(90); s,q=store.scan(self.cfg)
        self.assertTrue(q['issues']); self.assertFalse(store.publish(self.cfg,s,q))
        self.assertEqual(previous,(Path(self.cfg['worktree'])/'devices/test/manifest.json').read_bytes())
        source.unlink(); s,q=store.scan(self.cfg)
        self.assertEqual(s['records'][0]['input'],100)
        self.assertEqual(q['issues'][0]['code'],'source_missing_preserved')
    def test_log_relocation_preserves_coverage_without_double_counting(self):
        source=self.source();store.scan(self.cfg)
        archive=self.logs/'archived';archive.mkdir();source.rename(archive/'s.jsonl')
        snapshot,quality=store.scan(self.cfg)
        self.assertFalse(quality['issues']);self.assertEqual(len(snapshot['records']),1)
    def test_partial_json_does_not_publish(self):
        path=self.source();path.write_text(path.read_text()+'\n{"partial"')
        s,q=store.scan(self.cfg);self.assertTrue(q['issues']);self.assertFalse(store.publish(self.cfg,s,q))
    def test_no_data_week_is_not_usage_zero_claim(self):
        s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        report=store.aggregate(self.cfg['worktree'])
        self.assertGreaterEqual(len(report['weeks']),4)
        self.assertTrue(all(w['observation']=='no_records' for w in report['weeks']))
    def test_cross_device_dedup_and_conflict(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        other=dict(self.cfg,device='other');store.publish(other,s,q)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['totals']['responses'],1)
        s['records'][0]['input']=101;store.publish(other,s,q)
        report=store.aggregate(self.cfg['worktree'])
        self.assertEqual(report['quality']['problems'][0]['code'],'request_conflict')
        self.assertEqual(report['totals']['responses'],0)
    def test_integrity_rejects_tampered_shard(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        base=Path(self.cfg['worktree'])/'devices/test'
        entry=next(iter(store.read(base/'manifest.json')['shards'].values()))
        (base/entry['path']).write_text('{}')
        report=store.aggregate(self.cfg['worktree']); self.assertTrue(report['quality']['problems'])
    def test_claude_tool_diagnostics_dedup_and_no_content(self):
        path=self.logs/'claude.jsonl'
        call=dict(timestamp=self.ts,type='assistant',sessionId='s',message=dict(content=[dict(type='tool_use',id='c',name='Read',input=dict(file_path='/SECRET'))]))
        output=dict(timestamp=self.ts,type='user',sessionId='s',message=dict(content=[dict(type='tool_result',tool_use_id='c',is_error=True,content='SECRET'+'x'*9000)]))
        path.write_text('\n'.join(map(json.dumps,[call,call,output])))
        events,warnings=store.observations('Claude',path,store.now()-timedelta(days=1),store.now())
        self.assertEqual(len(events),2);self.assertTrue(events[1]['large']);self.assertTrue(events[1]['failed'])
        self.assertNotIn('SECRET',json.dumps(events));self.assertFalse(warnings)
    def test_year_boundary_and_kst(self):
        self.assertEqual(store.week('2027-01-01T12:00:00Z'),'2026-12-28')
        self.assertEqual(store.week('2026-09-13T15:00:00Z'),'2026-09-14')
    def test_lock_releases_on_error(self):
        with self.assertRaises(ValueError):
            with store.lock(self.cfg['state']): raise ValueError('test')
        with store.lock(self.cfg['state']):
            if os.name != 'nt':
                with self.assertRaises(RuntimeError):
                    with store.lock(self.cfg['state']):pass
    def test_font_license_line_endings_do_not_break_portable_approval(self):
        templates=self.root/'templates';templates.mkdir();template=templates/'report.html';template.write_text('sample')
        assets=self.root/'assets/usage-font';assets.mkdir(parents=True)
        license=assets/'OFL.txt';license.write_bytes(b'line1\nline2\n')
        first=render.fingerprint(template);license.write_bytes(b'line1\r\nline2\r\n')
        self.assertEqual(first,render.fingerprint(template))
    def test_approval_escaping_and_deterministic_render(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        report=store.aggregate(self.cfg['worktree']);report['devices'][0]['device']='<script>&'
        template=self.root/'template.html';template.write_text('<html>{{coverage}}{{input}}</html>')
        output=self.root/'out.html'; approval=self.root/'approved.json'
        with self.assertRaises(ValueError):render.render(report,template,output,approval)
        render.render(report,template,output,preview=True); first=output.read_bytes()
        self.assertNotIn('<script>',output.read_text());self.assertIn('&lt;script&gt;',output.read_text())
        store.atomic(approval,dict(fingerprint=render.fingerprint(template)))
        render.render(report,template,output,approval);self.assertEqual(first,output.read_bytes())
        template.write_text('changed')
        with self.assertRaises(ValueError):render.render(report,template,output,approval)
        self.assertEqual(first,output.read_bytes())

    def test_failed_manifest_swap_keeps_old_generation(self):
        self.source(); s,q=store.scan(self.cfg); store.publish(self.cfg,s,q)
        self.source(110); s,q=store.scan(self.cfg)
        original=store.atomic
        def fail(path,value):
            if Path(path).name=='manifest.json': raise OSError('simulated interruption')
            return original(path,value)
        with patch.object(store,'atomic',side_effect=fail):
            with self.assertRaises(OSError):store.publish(self.cfg,s,q)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['totals']['input'],100)
    def test_confirmed_correction_changes_value_and_preserves_evidence(self):
        self.source(); s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        self.source(90);store.scan(self.cfg)
        candidate_path=next((Path(self.cfg['state'])/'quarantine').glob('*.json'))
        candidate=store.read(candidate_path)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            tracker.accept_correction(self.cfg,candidate['source'],store.digest(candidate),'verified_source_correction')
        s,q=store.scan(self.cfg);self.assertFalse(q['issues']);store.publish(self.cfg,s,q)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['totals']['input'],90)
        self.assertTrue(list((Path(self.cfg['worktree'])/'devices/test/corrections').glob('*.json')))
    def test_task_linking_ambiguity_does_not_double_count(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        session=s['records'][0]['session'];base=Path(self.cfg['worktree'])/'devices/test/tasks'
        task=dict(id='issue-42',project='muring/demo',sessions=[session],status='completed',verification=[dict(name='regression',result='pass')])
        store.atomic(base/'one.json',task)
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['tasks'][0]['totals']['input'],100)
        store.atomic(base/'two.json',dict(task,id='issue-43'))
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['quality']['ambiguous_task_responses'],1)
        self.assertEqual(sum(t['totals']['input'] for t in report['tasks']),0)
        self.assertEqual(report['weeks'][-1]['task_states']['unclassified']['input'],100)
    def test_same_issue_id_different_project_is_not_a_conflict(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        base=Path(self.cfg['worktree'])/'devices/test/tasks'
        task=dict(id='issue-42',project='muring/demo',sessions=[s['records'][0]['session']],status='completed')
        store.atomic(base/'one.json',task);store.atomic(base/'two.json',dict(task,project='muring/other'))
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['quality']['task_conflicts'],0)
        self.assertEqual(sum(t['totals']['input'] for t in report['tasks']),100)
    def test_mixed_nonempty_legacy_format_is_flagged(self):
        path=self.source(); rows=[json.loads(x) for x in path.read_text().splitlines()]
        rows.insert(1,dict(type='event_msg',timestamp=self.ts,payload=dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=10)))))
        path.write_text('\n'.join(map(json.dumps,rows)))
        _,q=store.scan(self.cfg);self.assertTrue(q['issues'])
    def test_project_map_change_invalidates_cache(self):
        self.source();store.scan(self.cfg)
        self.cfg['projects']['demo']='muring/renamed';s,q=store.scan(self.cfg)
        self.assertEqual(q['files_parsed'],1);self.assertEqual(s['records'][0]['project'],'muring/renamed')
    def test_incompatible_schema_is_not_summed(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        path=Path(self.cfg['worktree'])/'devices/test/manifest.json';manifest=store.read(path);manifest['schema']=999;store.atomic(path,manifest)
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['totals']['input'],0);self.assertTrue(report['quality']['problems'])

class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.remote=self.root/'remote.git';subprocess.run(['git','init','--bare','-q',str(self.remote)],check=True)
        self.repo=self.root/'repo';subprocess.run(['git','init','-q',str(self.repo)],check=True)
        git(self.repo,'config','user.email','test@example.invalid');git(self.repo,'config','user.name','Test')
        (self.repo/'keep').write_text('original');git(self.repo,'add','.');git(self.repo,'commit','-qm','base');git(self.repo,'remote','add','origin',str(self.remote))
        git(self.repo,'push','origin','HEAD:main')
        self.cfg=dict(device='a',repo=str(self.repo),worktree=str(self.root/'wt'),state=str(self.root/'state'),branch='usage-data')
        tree=git(self.repo,'rev-parse','HEAD^{tree}')
        git(self.repo,'worktree','add','-qb','usage-data',self.cfg['worktree'])
        (self.repo/'keep').write_text('user work')
    def tearDown(self):self.tmp.cleanup()
    def test_sync_preserves_ordinary_worktree(self):
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        tracker.sync(self.cfg)
        self.assertEqual((self.repo/'keep').read_text(),'user work')
        self.assertEqual(git(self.cfg['worktree'],'status','--porcelain'),'')
        self.assertTrue(git(self.remote,'show-ref','refs/heads/usage-data'))
    def test_unrelated_file_and_wrong_branch_are_rejected(self):
        (Path(self.cfg['worktree'])/'bad').write_text('no')
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
        self.assertFalse(git(self.repo,'for-each-ref','refs/remotes/origin/usage-data'))
    def test_offline_commits_local_data_and_retries_later(self):
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        git(self.repo,'remote','set-url','origin',str(self.root/'missing'))
        with self.assertRaises(subprocess.CalledProcessError):tracker.sync(self.cfg)
        self.assertEqual(git(self.cfg['worktree'],'status','--porcelain'),'')
        git(self.repo,'remote','set-url','origin',str(self.remote));tracker.sync(self.cfg)
    def test_two_devices_merge_without_force_push(self):
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'one'});tracker.sync(self.cfg)
        second=self.root/'second';subprocess.run(['git','clone','-q','--branch','usage-data',str(self.remote),str(second)],check=True)
        git(second,'config','user.name','Test');git(second,'config','user.email','test@example.invalid')
        store.atomic(second/'devices/b/health.json',{'state':'two'});git(second,'add','.');git(second,'commit','-qm','b');git(second,'push')
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'three'});tracker.sync(self.cfg)
        self.assertTrue((Path(self.cfg['worktree'])/'devices/b/health.json').exists())
    def test_hidden_staged_unrelated_file_is_rejected(self):
        path=Path(self.cfg['worktree'])/'keep';path.write_text('staged other work');git(self.cfg['worktree'],'add','keep');path.write_text('original')
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
    def test_push_race_retries_without_force(self):
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        real=tracker.git; pushes=[]
        def race(path,*args,**kwargs):
            if args and args[0]=='push':
                pushes.append(args)
                if len(pushes)==1:raise subprocess.CalledProcessError(1,['git','push'])
            return real(path,*args,**kwargs)
        with patch.object(tracker,'git',side_effect=race):result=tracker.sync(self.cfg)
        self.assertEqual(result['attempts'],2);self.assertFalse(any('--force' in p for p in pushes))
    def test_generated_windows_and_macos_scheduler_formats(self):
        import xml.etree.ElementTree as ET, plistlib
        with patch.object(tracker.platform,'system',return_value='Windows'):
            result=tracker.scheduler(self.cfg,self.root/'config',False)
            ET.parse(Path(result['files'])/'ai-usage.xml')
        with patch.object(tracker.platform,'system',return_value='Darwin'):
            result=tracker.scheduler(self.cfg,self.root/'config',False)
            data=plistlib.loads((Path(result['files'])/'local.ai-usage.plist').read_bytes())
            self.assertEqual(data['StartInterval'],900);self.assertIn('scheduled',data['ProgramArguments'])
    def test_sync_failure_still_generates_local_json(self):
        logs=self.root/'logs';logs.mkdir()
        template=self.root/'template.html';template.write_text('<html></html>')
        self.cfg.update(roots=[dict(tool='Codex',path=str(logs))],projects={},template=str(template),reports=str(self.root/'reports'),improvements=str(self.root/'improvements.json'))
        with patch.object(tracker,'sync',side_effect=subprocess.CalledProcessError(1,['git','push'])):
            result=tracker.run(self.cfg,True)
        self.assertEqual(result['state'],'attention')
        self.assertTrue((self.root/'reports/latest.json').exists())
        self.assertEqual(store.read(Path(self.cfg['state'])/'sync.json')['state'],'failed')
    def test_scheduler_approval_gate(self):
        self.cfg['template']=str(self.root/'template');Path(self.cfg['template']).write_text('x')
        with self.assertRaises(ValueError):tracker.scheduler(self.cfg,self.root/'config',True)
        result=tracker.scheduler(self.cfg,self.root/'config',False)
        self.assertFalse(result['enabled'])

if __name__=='__main__':unittest.main()
