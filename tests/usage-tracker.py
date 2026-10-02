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
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/usage-report/scripts'
sys.path.insert(0, str(SCRIPTS))
import usage_store as store
import usage_tracker as tracker
import usage_render as render
import usage_session as session


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()

def activity_sample(name='known_work'):
    return next(c['activity'] for c in json.loads((Path(__file__).parent/'fixtures/ai-task-activity.json').read_text()) if c['name']==name)


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
        task=dict(id='issue-42',project='muring/demo',sessions=[session],status='completed',verification=[dict(name='regression',result='pass')], since=(store.now()-timedelta(days=1)).isoformat(), until=(store.now()+timedelta(days=1)).isoformat())
        store.atomic(base/'one.json',task)
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['tasks'][0]['totals']['input'],100)
        store.atomic(base/'two.json',dict(task,id='issue-43'))
        report=store.aggregate(self.cfg['worktree']);self.assertEqual(report['quality']['ambiguous_task_responses'],1)
        self.assertEqual(sum(t['totals']['input'] for t in report['tasks']),0)
        self.assertEqual(report['weeks'][-1]['task_states']['unclassified']['input'],100)
    def test_task_rejects_text_longer_than_blog_limit(self):
        path=self.root/'task.json'
        path.write_text(json.dumps(dict(id='issue-42',project='muring/demo',sessions=[],status='completed',verification=[dict(name='x'*301,result='pass')])))
        with self.assertRaisesRegex(ValueError,'300 characters'):tracker.record_task(self.cfg,path)
    def presentation(self):
        return dict(title='작업 결과',summary='실제로 확인한 결과',occurredAt=None,checks=[dict(title='회귀 검사',method='격리 fixture',result='pass',reason=None)],followUps=[dict(title='배포',status='delegated',note='소유 세션에서 수행')],knowledge=[],evidence=['로컬 검증'])
    def test_native_presentation_and_supplement_preserve_verification(self):
        task=dict(id='present',project='muring/demo',sessions=[],status='completed',verification=[dict(name='original',result='not_run')],presentation=self.presentation())
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):path=tracker.record_task(self.cfg,task)
        key=store.digest([task['project'],task['id']]);side=Path(self.cfg['worktree'])/'task-presentations'/(key+'.json')
        store.atomic(side,{k:task[k] for k in ('id','project','presentation')})
        report=store.aggregate(self.cfg['worktree']);t=report['tasks'][0]
        self.assertEqual(t['verification'],task['verification']);self.assertEqual(t['presentation'],task['presentation'])
        self.assertEqual(store.read(path)['presentation'],task['presentation'])
        changed=self.presentation();changed['title']='다른 결과'
        store.atomic(side,dict(id=task['id'],project=task['project'],presentation=changed))
        with self.assertRaisesRegex(ValueError,'conflict'):store.aggregate(self.cfg['worktree'])
    def test_supplement_only_missing_target_and_wrong_filename(self):
        task=dict(id='present',project='muring/demo',sessions=[],status='completed')
        root=Path(self.cfg['worktree']);key=store.digest([task['project'],task['id']])
        side=root/'task-presentations'/(key+'.json');store.atomic(side,dict(id=task['id'],project=task['project'],presentation=self.presentation()))
        with self.assertRaisesRegex(ValueError,'target missing'):store.aggregate(root)
        store.atomic(root/'devices/test/tasks/task.json',task)
        self.assertEqual(store.aggregate(root)['tasks'][0]['presentation'],self.presentation())
        self.assertNotIn('presentation',store.read(root/'devices/test/tasks/task.json'))
        side.rename(side.with_name('wrong.json'))
        with self.assertRaisesRegex(ValueError,'filename mismatch'):store.aggregate(root)
    def test_multidevice_presentation_conflict_is_an_error(self):
        root=Path(self.cfg['worktree']);t=dict(id='present',project='muring/demo',sessions=[],status='completed')
        store.atomic(root/'devices/a/tasks/task.json',t)
        store.atomic(root/'devices/b/tasks/task.json',dict(t,presentation=self.presentation()))
        with self.assertRaisesRegex(ValueError,'conflicting task'):store.aggregate(root)
    def test_invalid_presentation_contract(self):
        import usage_presentation as presentation
        for field,value in [('title','😀'*151),('occurredAt','2026-02-30T00:00:00Z'),('occurredAt','2026-01-01T00:00:00'),('checks',[dict(title='검사',method='',result='delegated',reason=None)]),('evidence',[False])]:
            p=self.presentation();p[field]=value
            with self.assertRaises(ValueError):presentation.validate(p)
        p=self.presentation();p['extra']='not allowed'
        with self.assertRaises(ValueError):presentation.validate(p)
        p=self.presentation();del p['knowledge']
        with self.assertRaises(ValueError):presentation.validate(p)
    def test_activity_native_sidecar_roundtrip_keeps_tokens_and_presentation(self):
        self.source();snapshot,quality=store.scan(self.cfg);store.publish(self.cfg,snapshot,quality)
        root=Path(self.cfg['worktree']);before=store.aggregate(root)['totals']
        task=dict(id='activity',project='muring/demo',sessions=[],status='completed',presentation=self.presentation(),activity=activity_sample())
        with patch.object(tracker,'guard',return_value=root):path=tracker.record_task(self.cfg,task)
        key=store.digest([task['project'],task['id']]);side=root/'task-activities'/(key+'.json')
        store.atomic(side,dict(version=1,project=task['project'],id=task['id'],activity=task['activity']))
        report=store.aggregate(root);self.assertEqual(before,report['totals']);self.assertEqual(report['tasks'][0]['activity'],task['activity']);self.assertEqual(report['tasks'][0]['presentation'],task['presentation'])
        task.pop('activity')
        with patch.object(tracker,'guard',return_value=root):tracker.record_task(self.cfg,task)
        self.assertEqual(store.read(path)['activity'],activity_sample())
        d=store.read(side);d['activity']['purpose']='충돌';store.atomic(side,d)
        with self.assertRaisesRegex(ValueError,'conflict'):store.aggregate(root)
    def test_activity_sidecar_missing_target_invalid_and_no_backfill(self):
        root=Path(self.cfg['worktree']);task=dict(id='activity',project='muring/demo',sessions=[],status='completed')
        store.atomic(root/'devices/a/tasks/task.json',task)
        self.assertNotIn('activity',store.aggregate(root)['tasks'][0])
        key=store.digest([task['project'],task['id']]);side=root/'task-activities'/(key+'.json')
        data=dict(version=1,id=task['id'],project=task['project'],activity=activity_sample('verified_date_only'));store.atomic(side,data)
        report=store.aggregate(root);self.assertEqual(report['tasks'][0]['activity']['timing']['precision'],'date');self.assertNotIn('activity',store.read(root/'devices/a/tasks/task.json'))
        (root/'devices/a/tasks/task.json').unlink()
        with self.assertRaisesRegex(ValueError,'target missing'):store.aggregate(root)
    def test_same_issue_id_different_project_is_not_a_conflict(self):
        self.source();s,q=store.scan(self.cfg);store.publish(self.cfg,s,q)
        base=Path(self.cfg['worktree'])/'devices/test/tasks'
        task=dict(id='issue-42',project='muring/demo',sessions=[s['records'][0]['session']],status='completed', since=(store.now()-timedelta(days=1)).isoformat(), until=(store.now()+timedelta(days=1)).isoformat())
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

class TaskTests(unittest.TestCase):
    setUp = StoreTests.setUp
    tearDown = StoreTests.tearDown
    source = StoreTests.source
    def test_longest_mapping_and_component_boundary(self):
        projects = {'demo': 'muring/fallback', '/work/demo': 'muring/demo',
                    '/work/demo/app': 'muring/app', 'C:\\Work\\Demo': 'muring/windows'}
        self.assertEqual(store.resolve_project('/work/demo/output/imagegen', projects), 'muring/demo')
        self.assertEqual(store.resolve_project('/work/demo/app/src', projects), 'muring/app')
        self.assertEqual(store.resolve_project('/work/demo-other/src', projects), 'unmapped')
        self.assertEqual(store.resolve_project('/else/demo', projects), 'muring/fallback')
        self.assertEqual(store.resolve_project('c:/work/DEMO/src', projects), 'muring/windows')

    def test_map_reclassification_preserves_request_totals(self):
        self.source(); before, _ = store.scan(self.cfg)
        self.cfg['projects']['/private/demo'] = 'muring/explicit'
        after, quality = store.scan(self.cfg)
        self.assertFalse(quality['issues'])
        self.assertEqual(store.token_totals(before['records']), store.token_totals(after['records']))
        self.assertEqual(after['records'][0]['project'], 'muring/explicit')

    def test_codex_identity_requires_matching_environment_and_metadata(self):
        self.source()
        with patch.dict(os.environ, {'CODEX_SESSION_ID':'s', 'CODEX_THREAD_ID':'s'}):
            identity = session.identify(self.cfg, 'Codex')
            self.assertEqual(identity['state'], 'verified')
            self.assertEqual(identity['session'], store.digest(['Codex', 's']))
        with patch.dict(os.environ, {'CODEX_SESSION_ID':'s', 'CODEX_THREAD_ID':'other'}):
            self.assertEqual(session.identify(self.cfg, 'Codex')['state'], 'unknown')
        with patch.dict(os.environ, {'CODEX_SESSION_ID':'missing', 'CODEX_THREAD_ID':'missing'}):
            self.assertEqual(session.identify(self.cfg, 'Codex')['state'], 'unknown')

    def test_claude_hook_and_explicit_identity(self):
        path=self.logs/'claude-id.jsonl'
        path.write_text(json.dumps(dict(sessionId='claude-id', cwd='/private/demo', type='user'))+'\n')
        self.cfg['roots']=[dict(tool='Claude',path=str(self.logs))]
        hook=self.root/'hook.json'
        store.atomic(hook, dict(session_id='claude-id',transcript_path=str(path)))
        self.assertEqual(session.identify(self.cfg,'Claude',hook_input=hook)['state'],'verified')
        self.assertEqual(session.identify(self.cfg,'Claude','wrong',path)['state'],'unknown')
        self.assertEqual(session.identify(self.cfg,'Claude')['state'],'unknown')
        store.atomic(hook, dict(session_id='claude-id',transcript_path=str(path),agent_id='child'))
        self.assertEqual(session.identify(self.cfg,'Claude',hook_input=hook)['state'],'unknown')
        path.write_text(path.read_text()+'{')
        self.assertEqual(session.identify(self.cfg,'Claude','claude-id',path)['state'],'unknown')

    def test_unbounded_legacy_and_half_open_cross_project_intervals(self):
        self.source(); snapshot, quality=store.scan(self.cfg);store.publish(self.cfg,snapshot,quality)
        row=snapshot['records'][0]; base=Path(self.cfg['worktree'])/'devices/test/tasks'
        task=dict(id='old',project='muring/demo',sessions=[row['session']],status='completed')
        store.atomic(base/'old.json',task)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['tasks'][0]['totals']['input'],0)
        boundary=row['timestamp'];before=(store.legacy.stamp(boundary)-timedelta(seconds=1)).isoformat()
        after=(store.legacy.stamp(boundary)+timedelta(seconds=1)).isoformat()
        interval=dict(session=row['session'],project='muring/demo',since=boundary,until=after)
        store.atomic(base/'new.json',dict(task,id='new',project='muring/target',intervals=[interval]))
        store.atomic(base/'prior.json',dict(task,id='prior',intervals=[dict(interval,since=before,until=boundary)]))
        report=store.aggregate(self.cfg['worktree'])
        self.assertEqual({t['id']:t['totals']['input'] for t in report['tasks']},{'old':0,'new':100,'prior':0})
        self.assertEqual(report['weeks'][-1]['groups'][0]['project'],'muring/demo')

    def test_unique_handles_retry_and_separate_segments(self):
        self.source()
        args=SimpleNamespace(id='task',project='muring/target',tool='Codex',session_id='s',transcript=None,hook_input=None)
        with patch.dict(os.environ, {'CODEX_SESSION_ID':'s','CODEX_THREAD_ID':'s'}):
            first=tracker.start_task(self.cfg,args);second=tracker.start_task(self.cfg,args)
        self.assertNotEqual(first['handle'],second['handle'])
        result=self.root/'result.json'
        store.atomic(result,dict(id='task',project='muring/target',status='completed',verification=[]))
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            one=tracker.finish_task(self.cfg,first['handle'],result)
            saved=Path(one['path']).read_bytes()
            self.assertEqual(tracker.finish_task(self.cfg,first['handle'],result)['state'],'already_finished')
            self.assertEqual(Path(one['path']).read_bytes(),saved)
            tracker.finish_task(self.cfg,second['handle'],result)
        task=store.read(one['path'])
        self.assertEqual(len(task['intervals']),2)
        self.assertEqual(task['project'],'muring/target')
        self.assertEqual(task['intervals'][0]['project'],'muring/demo')

    def test_finish_preserves_confirmed_activity_date_without_inferred_timestamp(self):
        self.source()
        args=SimpleNamespace(id='task',project='muring/target',tool='Codex',session_id='s',transcript=None,hook_input=None)
        with patch.dict(os.environ, {'CODEX_SESSION_ID':'s','CODEX_THREAD_ID':'s'}):
            start=tracker.start_task(self.cfg,args)
        activity=activity_sample('verified_date_only')
        result=self.root/'result.json'
        store.atomic(result,dict(id='task',project='muring/target',status='completed',activity=activity))
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            end=tracker.finish_task(self.cfg,start['handle'],result)
        saved=store.read(end['path'])
        self.assertEqual(saved['activity'],activity)
        self.assertTrue(saved['intervals'][0]['since'])
        self.assertTrue(saved['intervals'][0]['until'])
        self.assertIsNone(saved['activity']['timing']['occurredAt'])

    def test_new_task_collects_local_start_date_even_with_unknown_session(self):
        args=SimpleNamespace(id='dated',project='muring/demo',tool='Claude',session_id=None,transcript=None,hook_input=None)
        with patch.object(tracker,'now',return_value=store.legacy.stamp('2026-09-01T16:00:00Z')):
            start=tracker.start_task(self.cfg,args)
        result=self.root/'result.json'
        store.atomic(result,dict(id='dated',project='muring/demo',status='completed'))
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            end=tracker.finish_task(self.cfg,start['handle'],result)
        saved=store.read(end['path'])
        self.assertEqual(saved['sessions'],[])
        self.assertEqual(saved['activity']['timing']['occurredOn'],'2026-09-02')
        self.assertIsNone(saved['activity']['timing']['occurredAt'])
        self.assertEqual(saved['activity']['category'],'unknown')
        self.assertIsNone(saved['activity']['effects'])
        self.assertEqual(store.read(end['path']),store.read(tracker.finish_task(self.cfg,start['handle'],result)['path']))

    def test_date_collection_preserves_explicit_unknown_and_existing_sidecar(self):
        args=SimpleNamespace(id='dated',project='muring/demo',tool='Claude',session_id=None,transcript=None,hook_input=None)
        result=self.root/'result.json'
        for mode in ('explicit','sidecar','legacy'):
            with self.subTest(mode=mode):
                args.id=mode
                start=tracker.start_task(self.cfg,args)
                data=dict(id=mode,project=args.project,status='completed')
                if mode=='explicit':data['activity']=activity_sample('all_unknown')
                if mode=='sidecar':
                    side=Path(self.cfg['worktree'])/'task-activities'/(store.digest([args.project,mode])+'.json')
                    store.atomic(side,dict(version=1,project=args.project,id=mode,activity=activity_sample('all_unknown')))
                if mode=='legacy':
                    p=Path(self.cfg['state'])/'task-runs'/(start['handle']+'.json')
                    draft=store.read(p);draft.pop('occurred_on');draft.pop('date_timezone');store.atomic(p,draft)
                store.atomic(result,data)
                with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
                    end=tracker.finish_task(self.cfg,start['handle'],result)
                saved=store.read(end['path'])
                if mode=='explicit':self.assertEqual(saved['activity']['timing']['precision'],'unknown')
                else:self.assertNotIn('activity',saved)

    def test_unknown_identity_and_wrong_handle_target(self):
        args=SimpleNamespace(id='task',project='muring/demo',tool='Claude',session_id=None,transcript=None,hook_input=None)
        start=tracker.start_task(self.cfg,args)
        result=self.root/'result.json'
        store.atomic(result,dict(id='other',project='muring/demo',status='completed'))
        with self.assertRaisesRegex(ValueError,'match the handle'):
            tracker.finish_task(self.cfg,start['handle'],result)
        store.atomic(result,dict(id='task',project='muring/demo',status='completed'))
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            end=tracker.finish_task(self.cfg,start['handle'],result)
        self.assertEqual(store.read(end['path'])['sessions'],[])
        self.assertEqual(store.read(end['path'])['intervals'],[])

    def test_invalid_interval_is_rejected(self):
        task=dict(id='task',project='muring/demo',sessions=['a'*64],status='completed')
        for start,end in [('2026-10-01','2026-10-02'),('bad','bad'),('2026-10-02T00:00:00Z','2026-10-01T00:00:00Z')]:
            task['intervals']=[dict(session='a'*64,project='muring/demo',since=start,until=end)]
            with self.assertRaisesRegex(ValueError,'intervals require'):
                tracker.record_task(self.cfg,task)

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
    def supplement(self, root=None, ident='task', title='작업'):
        root=Path(root or self.cfg['worktree'])
        task=dict(id=ident,project='muring/demo',sessions=[],status='completed')
        store.atomic(root/'devices/a/tasks'/(ident+'.json'),task)
        presentation=dict(title=title,summary='',occurredAt=None,checks=[],followUps=[],knowledge=[],evidence=[])
        path=root/'task-presentations'/(store.digest([task['project'],ident])+'.json')
        store.atomic(path,dict(project=task['project'],id=ident,presentation=presentation))
        return path
    def clone_data(self):
        second=self.root/'second';subprocess.run(['git','clone','-q','--branch','usage-data',str(self.remote),str(second)],check=True)
        git(second,'config','user.name','Test');git(second,'config','user.email','test@example.invalid')
        return second
    def test_valid_supplements_sync_to_data_branch_only(self):
        p=self.supplement();tracker.sync(self.cfg)
        relative=p.relative_to(self.cfg['worktree']).as_posix()
        self.assertTrue(git(self.remote,'show','usage-data:'+relative))
        self.assertNotIn('task-presentations',git(self.remote,'ls-tree','--name-only','main'))
        self.assertEqual((self.repo/'keep').read_text(),'user work')
    def test_invalid_or_orphan_supplement_refused_before_commit(self):
        p=self.supplement();head=git(self.cfg['worktree'],'rev-parse','HEAD')
        d=store.read(p);d['presentation']['extra']='invalid';store.atomic(p,d)
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
        self.assertEqual(head,git(self.cfg['worktree'],'rev-parse','HEAD'))
        p=self.supplement();(Path(self.cfg['worktree'])/'devices/a/tasks/task.json').unlink()
        with self.assertRaisesRegex(ValueError,'target missing'):tracker.sync(self.cfg)
    def test_invalid_staged_sidecar_hidden_by_valid_worktree_refused(self):
        p=self.supplement();target=Path(self.cfg['worktree']);git(target,'add','devices')
        good=store.read(p);bad=dict(good,presentation=dict(good['presentation'],extra='invalid'))
        store.atomic(p,bad);git(target,'add','task-presentations');store.atomic(p,good)
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
    def test_sidecar_symlink_and_filename_mismatch_refused(self):
        p=self.supplement();original=p.read_text();p.unlink()
        outside=self.root/'outside.json';outside.write_text(original);p.symlink_to(outside)
        with self.assertRaises(ValueError):tracker.guard(self.cfg)
        p.unlink();wrong=p.with_name('b'*64+'.json');wrong.write_text(original)
        with self.assertRaisesRegex(ValueError,'filename mismatch'):tracker.guard(self.cfg)
    def test_concurrent_sidecar_edits_are_held(self):
        p=self.supplement();tracker.sync(self.cfg);other=self.clone_data()
        self.supplement(other,title='원격');git(other,'add','.');git(other,'commit','-qm','remote');git(other,'push')
        remote=git(self.remote,'rev-parse','usage-data');self.supplement(title='로컬')
        with self.assertRaisesRegex(ValueError,'concurrent edits'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))
        self.assertEqual(store.read(p)['presentation']['title'],'로컬')
    def test_remote_task_native_conflict_blocks_merged_push(self):
        self.supplement();tracker.sync(self.cfg);other=self.clone_data()
        task=other/'devices/a/tasks/task.json';d=store.read(task)
        d['presentation']=dict(title='원격 원본',summary='',occurredAt=None,checks=[],followUps=[],knowledge=[],evidence=[])
        store.atomic(task,d);git(other,'add','.');git(other,'commit','-qm','remote');git(other,'push')
        remote=git(self.remote,'rev-parse','usage-data')
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        with self.assertRaisesRegex(ValueError,'conflict'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))
    def test_disjoint_remote_supplement_merges(self):
        self.supplement();tracker.sync(self.cfg);other=self.clone_data()
        self.supplement(other,ident='second');git(other,'add','.');git(other,'commit','-qm','remote');git(other,'push')
        self.supplement(ident='third');tracker.sync(self.cfg)
        self.assertEqual(len(store.aggregate(self.cfg['worktree'])['tasks']),3)
    def activity_supplement(self, root=None):
        root=Path(root or self.cfg['worktree']);p=self.supplement(root)
        d=store.read(p);path=root/'task-activities'/p.name
        store.atomic(path,dict(version=1,project=d['project'],id=d['id'],activity=activity_sample()))
        return path
    def test_activity_sync_is_private_branch_only(self):
        p=self.activity_supplement();tracker.sync(self.cfg)
        self.assertEqual(json.loads(git(self.remote,'show','usage-data:'+p.relative_to(self.cfg['worktree']).as_posix()))['activity'],activity_sample())
        self.assertNotIn('task-activities',git(self.remote,'ls-tree','--name-only','main'))
    def test_invalid_staged_activity_hidden_by_valid_worktree_refused(self):
        p=self.activity_supplement();good=store.read(p);bad=store.read(p);bad['activity']['effects']=[{}]
        store.atomic(p,bad);git(self.cfg['worktree'],'add','devices','task-presentations','task-activities');store.atomic(p,good)
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
    def test_remote_activity_native_conflict_blocks_push(self):
        self.activity_supplement();tracker.sync(self.cfg);other=self.clone_data()
        task=other/'devices/a/tasks/task.json';d=store.read(task);d['activity']=activity_sample();d['activity']['purpose']='원격 다른 결과';store.atomic(task,d)
        git(other,'add','.');git(other,'commit','-qm','remote');git(other,'push');remote=git(self.remote,'rev-parse','usage-data')
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        with self.assertRaisesRegex(ValueError,'conflict'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))

    def test_knowledge_staged_and_remote_conflict_blocks_push(self):
        p=self.activity_supplement();good=store.read(p);good['activity']=activity_sample('knowledge_direct')
        store.atomic(p,good);tracker.sync(self.cfg)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['tasks'][0]['activity'],good['activity'])
        bad=store.read(p);bad['activity']['knowledgeDecisions'][0]['verification']=None
        store.atomic(p,bad);git(self.cfg['worktree'],'add','task-activities');store.atomic(p,good)
        with self.assertRaises(ValueError):tracker.sync(self.cfg)
        git(self.cfg['worktree'],'add','task-activities')
        other=self.clone_data();task=other/'devices/a/tasks/task.json';d=store.read(task)
        d['activity']=activity_sample('knowledge_direct');d['activity']['knowledgeDecisions'][0]['reason']='원격의 다른 판단'
        store.atomic(task,d);git(other,'add','.');git(other,'commit','-qm','conflicting decision');git(other,'push')
        remote=git(self.remote,'rev-parse','usage-data')
        with self.assertRaisesRegex(ValueError,'conflict'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))

    def review_record(self, device=None):
        from usage_knowledge_reviews import fingerprint, persist
        p=self.activity_supplement()
        target=store.read(p)
        cases=json.loads((Path(__file__).parent/'fixtures/knowledge-reviews.json').read_text())
        value=next(c['review'] for c in cases if c['name']=='matched')
        value.update(project=target['project'],taskId=target['id'])
        for row in value['result']['rows']:row.update(project=target['project'],task=target['id'])
        value['sourceDigest']=fingerprint(value['project'],value['taskId'],value['source'])
        return Path(persist(dict(self.cfg,device=device or self.cfg['device']),value))

    def test_review_sync_roundtrip_and_immutable_history(self):
        from usage_knowledge_reviews import persist
        p=self.review_record();tracker.sync(self.cfg)
        value=store.read(p)
        self.assertEqual(json.loads(git(self.remote,'show','usage-data:'+p.relative_to(self.cfg['worktree']).as_posix())),value)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews'],[value])
        failure=dict(value,id='b'*32,status='failed',result=None,error='Reconciliation failed')
        persist(self.cfg,failure);tracker.sync(self.cfg)
        self.assertEqual(len(store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']),2)
        remote=git(self.remote,'rev-parse','usage-data')
        value['reviewedAt']='2026-10-03T00:00:00Z';store.atomic(p,value)
        with self.assertRaisesRegex(ValueError,'preserved'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))
        p.unlink()
        with self.assertRaisesRegex(ValueError,'preserved'):tracker.guard(self.cfg)

    def test_review_invalid_staged_hidden_by_valid_worktree_is_rejected(self):
        p=self.review_record();good=store.read(p);bad=store.read(p);bad['result']['rows'][0]['reason']='Wrong reason'
        store.atomic(p,bad);git(self.cfg['worktree'],'add','devices','task-presentations','task-activities');store.atomic(p,good)
        with self.assertRaises(ValueError):tracker.sync(self.cfg)

    def test_remote_review_attempt_conflict_blocks_push(self):
        p=self.review_record();tracker.sync(self.cfg);other=self.clone_data()
        value=store.read(p);value['reviewedAt']='2026-10-03T00:00:00Z'
        store.atomic(other/'devices/other/knowledge-reviews'/p.name,value)
        git(other,'add','.');git(other,'commit','-qm','review conflict');git(other,'push')
        remote=git(self.remote,'rev-parse','usage-data')
        with self.assertRaisesRegex(ValueError,'Conflicting'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))

    def handoff_supplement(self):
        p=self.activity_supplement();d=store.read(p)
        a=activity_sample('handoff_dispatch_accepted')
        a['handoffs'][0]['from']=dict(project=d['project'],taskId=d['id'])
        d['activity']=a;store.atomic(p,d)
        return p

    def test_handoff_roundtrip_and_history_removal_refused(self):
        p=self.handoff_supplement();tracker.sync(self.cfg)
        data=store.read(p)
        self.assertEqual(store.aggregate(self.cfg['worktree'])['tasks'][0]['activity'],data['activity'])
        remote=git(self.remote,'rev-parse','usage-data')
        data['activity'].pop('handoffs');store.atomic(p,data)
        with self.assertRaisesRegex(ValueError,'handoff'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))

    def test_handoff_cross_task_remote_conflict_blocks_push(self):
        p=self.handoff_supplement();tracker.sync(self.cfg);other=self.clone_data()
        a=store.read(p)['activity'];a['handoffs'][0]['request']='원격 요청 충돌'
        store.atomic(other/'devices/b/tasks/recipient.json',dict(id='recipient-task',project='example/app',status='in_progress',activity=a))
        git(other,'add','.');git(other,'commit','-qm','remote handoff');git(other,'push')
        remote=git(self.remote,'rev-parse','usage-data')
        store.atomic(Path(self.cfg['worktree'])/'devices/a/health.json',{'state':'ok'})
        with self.assertRaisesRegex(ValueError,'handoff.*conflict'):tracker.sync(self.cfg)
        self.assertEqual(remote,git(self.remote,'rev-parse','usage-data'))

    def test_handoff_endpoint_and_hidden_invalid_stage_refused(self):
        p=self.handoff_supplement();good=store.read(p);bad=store.read(p)
        bad['activity']['handoffs'][0]['from']['project']='unrelated/project'
        store.atomic(p,bad)
        with self.assertRaisesRegex(ValueError,'endpoint'):tracker.guard(self.cfg)
        git(self.cfg['worktree'],'add','devices','task-presentations','task-activities')
        store.atomic(p,good)
        with self.assertRaisesRegex(ValueError,'endpoint'):tracker.guard(self.cfg)
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
        self.assertEqual(result['revision'],git(self.cfg['worktree'],'rev-parse','HEAD'))
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
