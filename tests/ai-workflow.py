#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
usage=module('usage','skills/usage-report/scripts/usage_report.py')
waiter=module('waiter','skills/wait-deploy/scripts/wait_deploy.py')
verify=module('verify','skills/verify-changes/scripts/verify_changes.py')
from worktree import snapshot

class UsageTests(unittest.TestCase):
 def test_diagnostics_redacts_content_and_counts_calls_once(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'s.jsonl';t='2026-09-14T01:00:00Z'
   def row(kind,call,**values):return dict(timestamp=t,type='response_item',payload=dict(type=kind,call_id=call,**values))
   call=row('custom_tool_call','a',name='exec',input='await tools.exec_command({cmd:"PRIVATE_COMMAND"})')
   data=[call,call,row('custom_tool_call','b',name='exec',input=call['payload']['input']),row('custom_tool_call_output','a',output=[dict(type='text',text='PRIVATE_OUTPUT'+'x'*8100)]),row('function_call_output','b',output='Warning: truncated output')]
   path.write_text('\n'.join(json.dumps(x) for x in data))
   records=[dict(tool='Codex',source=str(path),input=100),dict(tool='Codex',source=str(path),input=200)]
   warnings=[];d=usage.diagnose(records,datetime(2026,9,14,tzinfo=timezone.utc),datetime(2026,9,15,tzinfo=timezone.utc),warnings)
   self.assertEqual(d['tool_calls'],2);self.assertEqual(d['repeated_exact_calls']['exec'],1)
   self.assertEqual(d['outputs_over_8000_chars'],1);self.assertEqual(d['truncation_markers'],1)
   self.assertEqual(d['nested_tool_mentions']['exec_command'],2)
   self.assertNotIn('PRIVATE',json.dumps(d));self.assertFalse(warnings)
 def test_claude_diagnostics_are_supported_by_existing_cli_api(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'s.jsonl';t='2026-09-14T01:00:00Z'
   rows=[dict(timestamp=t,type='assistant',sessionId='s',message=dict(content=[dict(type='tool_use',id='c',name='Read',input=dict(file_path='PRIVATE_PATH'))])),dict(timestamp=t,type='user',sessionId='s',message=dict(content=[dict(type='tool_result',tool_use_id='c',content='PRIVATE_OUTPUT'+'x'*9000,is_error=False)]))]
   path.write_text('\n'.join(map(json.dumps,rows)))
   import sys
   sys.path.insert(0,str(ROOT/'skills/usage-report/scripts'))
   warnings=[];result=usage.diagnose([dict(tool='Claude',source=str(path),input=10)],datetime(2026,9,14,tzinfo=timezone.utc),datetime(2026,9,15,tzinfo=timezone.utc),warnings)
   self.assertEqual(result['tool_calls'],1);self.assertEqual(result['outputs_over_8000_chars'],1)
   self.assertNotIn('PRIVATE',json.dumps(result));self.assertFalse(warnings)
 def test_cli_rolling_days_filters_tool_before_scan(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);p=root/'.codex/sessions';p.mkdir(parents=True)
   p.joinpath('s.jsonl').write_text(json.dumps(dict(timestamp='2026-09-14T00:00:00Z',type='token_usage_record',payload=dict(response_id='one',usage=dict(input_tokens=7,output_tokens=3)))))
   cmd=[sys.executable,str(ROOT/'skills/usage-report/scripts/usage_report.py'),'--home',str(root),'--config',str(root/'unused.json'),'--tool','codex','--days','7','--until','2026-09-20T00:00:00+00:00','--json']
   result=json.loads(subprocess.check_output(cmd,text=True))
   self.assertEqual(result['totals']['total'],10);self.assertEqual(result['period']['since'],'2026-09-13T00:00:00+00:00')
   self.assertTrue(all(r['tool']=='Codex' for r in result['roots']));self.assertFalse(result['warnings'])
   self.assertNotEqual(subprocess.run(cmd+['--since','2026-09-14'],capture_output=True).returncode,0)
   self.assertNotEqual(subprocess.run(cmd+['--days','0'],capture_output=True).returncode,0)
 def test_stream_duplicates_boundaries_worktree_and_subagent(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);c=root/'codex';a=root/'claude';c.mkdir();a.mkdir()
   u=dict(input_tokens=100,cached_input_tokens=80,output_tokens=5,reasoning_output_tokens=2)
   def event(t,typ,payload):return dict(timestamp=t,type=typ,payload=payload)
   rows=[event('2026-09-13T14:00:00Z','session_meta',dict(id='parent',cwd='/home/u/orca/workspaces/demo/branch')),
    event('2026-09-13T14:00:01Z','token_usage_record',dict(response_id='old',usage=u)),
    event('2026-09-13T15:00:00Z','token_usage_record',dict(response_id='one',usage=u)),
    event('2026-09-13T15:00:00Z','token_usage_record',dict(response_id='one',usage=u)),
    event('2026-09-13T15:00:01Z','event_msg',dict(type='token_count',info=dict(total_token_usage=u))),
    event('2026-09-14T15:00:00Z','token_usage_record',dict(response_id='excluded',usage=u))]
   (c/'s.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
   def assistant(output):return dict(timestamp='2026-09-13T16:00:00Z',type='assistant',cwd='/home/u/demo',requestId='r',message=dict(id='m',model='claude',usage=dict(input_tokens=3,cache_read_input_tokens=70,cache_creation_input_tokens=20,output_tokens=output,output_tokens_details=None)))
   (a/'main.jsonl').write_text('\n'.join(json.dumps(x) for x in [assistant(2),assistant(7),dict(type='cost-state',totalCostUSD=99)]))
   sub=a/'subagents';sub.mkdir();x=assistant(4);x['message']['id']='child';(sub/'child.jsonl').write_text(json.dumps(x))
   records,sessions,stats,warnings=usage.collect([('Codex',c),('Codex',c),('Claude',a)],datetime(2026,9,13,15,tzinfo=timezone.utc),datetime(2026,9,14,15,tzinfo=timezone.utc))
   self.assertEqual(len(records),3);self.assertEqual(stats['duplicate_records'],2)
   self.assertEqual(sum(r['input']+r['output'] for r in records),105+100+97)
   self.assertTrue(any(s['subagent'] for s in sessions));self.assertEqual(records[0]['project'],'demo');self.assertFalse(warnings)
 def test_old_cumulative_logs_use_delta_and_warn_on_reset(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'s.jsonl';rows=[dict(type='session_meta',payload=dict(id='s',cwd='/x',timestamp='2026-09-12T00:00:00Z'))]
   for t,n in [('2026-09-13T14:59:00Z',100),('2026-09-13T15:00:00Z',150),('2026-09-13T15:01:00Z',150),('2026-09-13T15:02:00Z',10)]:
    rows.append(dict(timestamp=t,type='event_msg',payload=dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=n,output_tokens=0),last_token_usage=dict(input_tokens=10,output_tokens=0)))))
   path.write_text('\n'.join(json.dumps(x) for x in rows))
   records,_,_,warnings=usage.collect([('Codex',Path(tmp))],datetime(2026,9,13,15,tzinfo=timezone.utc),datetime(2026,9,14,tzinfo=timezone.utc))
   self.assertEqual(sum(r['input'] for r in records),60);self.assertIn('reset',warnings[0])

class WaitTests(unittest.TestCase):
 def row(self,state,name='deploy'):return dict(name=name,state=state)
 def test_missing_failed_and_skipped_are_not_success(self):
  self.assertEqual(waiter.evaluate([],['deploy'])[0],'pending')
  self.assertEqual(waiter.evaluate([self.row('success','lint')],['deploy'])[0],'pending')
  self.assertEqual(waiter.evaluate([self.row('failure')],['deploy'])[0],'failure')
  self.assertEqual(waiter.evaluate([self.row('skipped')],['deploy'])[0],'failure')
 def test_one_process_waits_until_success_and_only_notifies_changes(self):
  now=[0];events=[];states=iter(['pending','pending','success'])
  result=waiter.wait(lambda t:[self.row(next(states))],['deploy'],50,2,10,events.append,lambda:now[0],lambda t:now.__setitem__(0,now[0]+t))
  self.assertEqual(result['state'],'success');self.assertEqual(result['polls'],3);self.assertEqual(len(events),2)
 def test_timeout_no_status_does_not_succeed(self):
  now=[0];result=waiter.wait(lambda t:[],['deploy'],5,2,4,clock=lambda:now[0],sleep=lambda t:now.__setitem__(0,now[0]+t))
  self.assertEqual(result['state'],'timeout');self.assertEqual(now[0],5)
 def test_paginated_reruns_use_latest(self):
  with patch.object(waiter,'gh_json',side_effect=[[[dict(id=2,context='deploy',state='success')],[dict(id=1,context='deploy',state='failure')]], [{'check_runs':[dict(id=3,name='tests',status='completed',conclusion='success',app=dict(id=1))]}]]):
   rows=waiter.status_rows('owner/repo','a'*40)
  self.assertEqual(waiter.evaluate(rows,[])[0],'success');self.assertEqual(len(rows),2)

class VerifyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  subprocess.run(['git','init','-q',str(self.root)],check=True)
  self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
  (self.root/'a.txt').write_text('old');self.git('add','.');self.git('commit','-qm','initial')
 def tearDown(self):self.temp.cleanup()
 def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args])
 def test_snapshot_includes_staged_unstaged_untracked_and_deleted(self):
  (self.root/'a.txt').unlink();(self.root/'staged.txt').write_text('a');self.git('add','staged.txt')
  (self.root/'staged.txt').write_text('b');(self.root/'new space.txt').write_text('c')
  first=snapshot(self.root);self.assertEqual({f['path'] for f in first['files']},{'a.txt','staged.txt','new space.txt'})
  (self.root/'new space.txt').write_text('d');self.assertNotEqual(first['fingerprint'],snapshot(self.root)['fingerprint'])
 def test_named_checks_and_dependency_changes(self):
  checks=[dict(name='render',command=['true'],paths=['src/lib/markdown/*','yarn.lock']),dict(name='other',command=['true'],paths=['other/*'])]
  self.assertEqual([c['name'] for c in verify.choose(checks,['src/lib/markdown/deep/x.ts'],[])],['render'])
  self.assertEqual(len(verify.choose(checks,[],[],config_changed=True)),2)
  with self.assertRaises(ValueError):verify.choose(checks,[],['typo'])
 def test_failure_log_and_timeout(self):
  a=verify.run_check(dict(name='fail',command=[sys.executable,'-c','print("diagnostic");raise SystemExit(7)']),self.root,self.root,1)
  self.assertEqual(a['status'],'failed');self.assertEqual(a['exit_code'],7);self.assertIn('diagnostic',a['failure_tail'])
  b=verify.run_check(dict(name='slow',command=[sys.executable,'-c','import time;time.sleep(5)'],timeout=.05),self.root,self.root,2)
  self.assertEqual(b['status'],'timeout')

if __name__=='__main__':unittest.main()
