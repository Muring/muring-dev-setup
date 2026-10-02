#!/usr/bin/env python3
"""Changed Git-publisher boundaries only. All GitHub/network calls are synthetic."""
import copy
from datetime import datetime,timedelta,timezone
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/usage-report/scripts'))
import usage_git_publish as gp
import usage_publish as exporter
import usage_store as store
import usage_tracker as tracker

REV='a'*40;NEW='b'*40;AT=datetime(2026,10,2,1,tzinfo=timezone.utc)

def receipt(state='applied',revision=REV,sequence=12):
    return dict(schema=1,state=state,requestedSequence=sequence,requestedRevision=revision,appliedSequence=sequence+(state=='superseded'),appliedRevision=NEW if state=='superseded' else revision)

def run(request_id,status='completed',conclusion='success'):
    return dict(id=101,run_number=12,run_attempt=1,workflow_id=7,path=gp.WORKFLOW_PATH+'@main',head_sha='c'*40,repository={'full_name':'owner/repo'},display_title='ai-usage-'+request_id,event='workflow_dispatch',head_branch='main',status=status,conclusion=conclusion)

class FakeGitHub:
    def __init__(self):self.sent=[];self.runs={};self.value=receipt();self.lost=False;self.includes=True
    def dispatch(self,revision,request_id):
        self.sent.append((revision,request_id))
        if self.lost:raise RuntimeError('synthetic lost response')
    def find_run(self,request_id):return self.runs.get(request_id)
    def receipt(self,r):return self.value
    def contains_revision(self,a,b):return self.includes

class GitPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cfg=dict(state=str(self.root/'state'),device='device-a',publisher=dict(mode='git-workflow',repository='owner/repo'))
        self.gh=FakeGitHub();self.clock=patch.object(gp,'now',return_value=AT);self.clock.start()
    def tearDown(self):self.clock.stop();self.tmp.cleanup()
    def publisher(self):return gp.Publisher(self.cfg,self.gh)
    def started(self):
        p=self.publisher();p.enqueue(REV);result=p.retry()
        self.assertEqual(result['pending'],1);self.assertEqual(result['requests'][0]['state'],'accepted')
        return p,self.gh.sent[-1][1]

    def test_dispatch_contract_and_credentials_not_embedded(self):
        calls=[]
        def command(args,**kwargs):
            calls.append((args,kwargs))
            response='' if '--input' in args else json.dumps({'id':7,'path':gp.WORKFLOW_PATH})
            return SimpleNamespace(returncode=0,stdout=response,stderr='')
        with patch.object(gp.subprocess,'run',side_effect=command):gp.GitHub('owner/repo').dispatch(REV,'1'*32)
        self.assertEqual(json.loads(calls[-1][1]['input']),dict(ref='main',inputs=dict(requested_revision=REV,request_id='1'*32)))
        self.assertIn('--hostname',calls[-1][0]);self.assertNotIn('Authorization',' '.join(calls[-1][0]))
        self.assertEqual(calls[-1][1]['env']['GH_PROMPT_DISABLED'],'1')

    def test_restart_reuses_revision_and_checks_run_before_redispatch(self):
        p,ident=self.started();self.publisher().enqueue(REV)
        self.gh.runs[ident]=run(ident,'in_progress',None)
        result=self.publisher().retry();self.assertEqual(result['requests'][0]['state'],'running')
        self.assertEqual(len(self.gh.sent),1)
        self.gh.runs[ident]=run(ident)
        result=self.publisher().retry();self.assertEqual(result['pending'],0)
        self.assertEqual(result['requests'][0]['receipt'],receipt())
        self.publisher().retry();self.assertEqual(len(self.gh.sent),1)

    def test_lost_dispatch_response_is_found_without_duplicate_call(self):
        self.gh.lost=True;p=self.publisher();p.enqueue(REV);p.retry()
        ident=self.gh.sent[0][1];self.assertEqual(p.status()['requests'][0]['attempts'][0]['state'],'dispatch_unknown')
        self.gh.runs[ident]=run(ident)
        self.assertEqual(self.publisher().retry()['pending'],0);self.assertEqual(len(self.gh.sent),1)

    def test_not_found_is_unknown_then_new_attempt_id_on_later_invocation(self):
        p,ident=self.started();p.retry();self.assertEqual(len(self.gh.sent),1)
        with patch.object(gp,'now',return_value=AT+timedelta(minutes=11)):
            self.assertEqual(p.retry()['requests'][0]['state'],'accepted')
            p.retry()
        self.assertEqual(len(self.gh.sent),2);self.assertNotEqual(ident,self.gh.sent[-1][1])
        self.assertEqual(len(p.status()['requests'][0]['attempts']),2)

    def test_failed_cancelled_or_missing_receipt_never_complete(self):
        p,ident=self.started();self.gh.runs[ident]=run(ident,conclusion='cancelled')
        self.assertEqual(p.retry()['requests'][0]['state'],'run_failed');self.assertEqual(len(self.gh.sent),1)
        p.retry();second=self.gh.sent[-1][1];self.gh.runs[second]=run(second)
        self.gh.value={'accepted':True}
        result=p.retry();self.assertEqual(result['pending'],1);self.assertEqual(result['requests'][0]['state'],'receipt_unverified')
        self.assertIsNone(result['requests'][0]['receipt'])

    def test_receipt_ancestry_and_sequence_and_superseded_outcome(self):
        p,ident=self.started();self.gh.runs[ident]=run(ident);self.gh.includes=False
        self.assertEqual(p.retry()['pending'],1)
        self.gh.includes=True;p.retry();ident=self.gh.sent[-1][1];self.gh.runs[ident]=run(ident)
        self.gh.value=receipt('superseded',NEW)
        result=p.retry();self.assertEqual(result['requests'][0]['state'],'superseded')
        self.assertEqual(result['pending'],0)
        for mutate in (lambda r:r.update(requestedSequence=True),lambda r:r.update(requestedSequence=11),lambda r:r.update(appliedRevision='z'*40),lambda r:r.update(state='applied')):
            bad=receipt('superseded');mutate(bad)
            with self.assertRaises(ValueError):gp.validate_receipt(bad,12)

    def test_run_scope_checks_exact_workflow_request_and_main(self):
        valid=run('1'*32);gp.validate_run(valid,'1'*32,'owner/repo',7)
        for field,value in [('display_title','ai-usage-wrong'),('event','push'),('head_branch','usage-data'),('workflow_id',8),('path',gp.WORKFLOW_PATH+'@evil'),('repository',{'full_name':'other/repo'}),('run_number',True)]:
            bad=copy.deepcopy(valid);bad[field]=value
            with self.assertRaises(ValueError):gp.validate_run(bad,'1'*32,'owner/repo',7)

    def test_actual_github_adapter_filters_and_validates_run(self):
        api=gp.GitHub('owner/repo')
        responses=[{'id':7,'path':gp.WORKFLOW_PATH},{'workflow_runs':[run('2'*32),run('1'*32)]}]
        with patch.object(api,'api',side_effect=responses):self.assertEqual(api.find_run('1'*32)['id'],101)
        bad=run('1'*32);bad['head_branch']='usage-data'
        with patch.object(api,'api',return_value={'workflow_runs':[bad]}):
            with self.assertRaises(ValueError):api.find_run('1'*32)

    def test_artifact_bound_to_run_and_single_receipt_only(self):
        api=gp.GitHub('owner/repo');r=run('1'*32)
        artifact=dict(name=gp.ARTIFACT,expired=False,size_in_bytes=500,workflow_run={'id':101})
        def download(args,input=None):
            directory=Path(args[args.index('--dir')+1]);(directory/'receipt.json').write_text(json.dumps(receipt()))
            return ''
        with patch.object(api,'api',return_value={'artifacts':[artifact]}),patch.object(api,'command',side_effect=download):self.assertEqual(api.receipt(r),receipt())
        artifact['workflow_run']['id']=102
        with patch.object(api,'api',return_value={'artifacts':[artifact]}),patch.object(api,'command',side_effect=AssertionError('downloaded unbound artifact')):
            with self.assertRaises(ValueError):api.receipt(r)

    def test_daily_collect_once_sync_failure_then_retry(self):
        calls=[]
        def collect():calls.append('collect');return {'state':'ok'}
        def fail():raise RuntimeError('synthetic sync failed')
        first=gp.daily(self.cfg,collect,fail,self.gh)
        self.assertEqual(first['sync'],'failed');self.assertEqual(self.gh.sent,[])
        second=gp.daily(self.cfg,collect,lambda:{'state':'ok','revision':REV},self.gh)
        self.assertEqual(second['collection'],'already_collected');self.assertEqual(calls,['collect'])
        self.assertEqual(len(self.gh.sent),1)

    def test_failed_collection_blocks_sync_but_pending_run_still_verifies(self):
        p,ident=self.started();self.gh.runs[ident]=run(ident)
        def fail():raise ValueError('collection invalid')
        def forbidden():raise AssertionError('sync after invalid collection')
        result=gp.daily(self.cfg,fail,forbidden,self.gh)
        self.assertEqual(result['collection'],'failed');self.assertEqual(result['publisher']['pending'],0)
        gp.daily(self.cfg,fail,forbidden,self.gh,retry_only=True)

    def test_manual_sync_marker_recovers_enqueue_crash(self):
        store.atomic(Path(self.cfg['state'])/'sync.json',dict(state='ok',revision=REV))
        gp.daily(self.cfg,lambda:None,lambda:None,self.gh,retry_only=True)
        self.assertEqual(self.gh.sent[0][0],REV)

    def test_queue_failure_preserves_successful_sync_and_retries_without_collect(self):
        collect_calls=[]
        def collect():collect_calls.append(1);return {'state':'ok'}
        with patch.object(gp.Publisher,'enqueue',side_effect=OSError('synthetic disk error')):
            first=gp.daily(self.cfg,collect,lambda:{'state':'ok','revision':REV},self.gh)
        self.assertEqual(first['sync']['state'],'ok');self.assertEqual(first['queue'],'failed')
        gp.daily(self.cfg,collect,lambda:{'state':'ok','revision':REV},self.gh)
        self.assertEqual(len(collect_calls),1);self.assertEqual(len(self.gh.sent),1)

    def test_corrupt_persisted_receipt_is_not_completion(self):
        p,ident=self.started();path,item=p.requests()[0];item['receipt']=receipt();item['state']='applied'
        store.atomic(path,item)
        with self.assertRaises(ValueError):self.publisher().retry()

    def test_cli_routes_new_mode_without_real_git_or_network(self):
        config=self.root/'config.json';store.atomic(config,self.cfg)
        argv=['tracker','--config',str(config),'scheduled']
        with patch.object(sys,'argv',argv),patch.object(tracker,'guard',return_value=self.root),patch.object(tracker,'git',return_value='git@github.com:owner/repo.git'),patch.object(tracker,'run',return_value={'state':'ok'}) as collected,patch.object(tracker,'sync',return_value={'state':'ok','revision':REV}),patch.object(gp,'GitHub',return_value=self.gh),patch('builtins.print'):
            self.assertEqual(tracker.main(),0);self.assertEqual(tracker.main(),0)
            self.assertEqual(collected.call_count,1)
        self.assertEqual(len(self.gh.sent),1)

    def test_configuration_and_existing_guard_boundary_not_relaxed(self):
        gp.validate_remote('owner/repo','https://github.com/owner/repo.git')
        for remote in ('https://evil.test/owner/repo','https://secret@github.com/owner/repo','git@github.com:other/repo.git'):
            with self.assertRaises(ValueError):gp.validate_remote('owner/repo',remote)
        cfg=copy.deepcopy(self.cfg);cfg['delivery']={'mode':'device-v1'}
        with self.assertRaises(ValueError):gp.Publisher(cfg,self.gh)
        self.publisher();cfg=copy.deepcopy(self.cfg);cfg['publisher']['repository']='other/repo'
        with self.assertRaises(ValueError):gp.Publisher(cfg,self.gh)

    def test_explicit_sync_dispatches_and_status_does_not_contact_github(self):
        config=self.root/'config.json';store.atomic(config,self.cfg)
        with patch.object(sys,'argv',['tracker','--config',str(config),'sync']),patch.object(tracker,'guard',return_value=self.root),patch.object(tracker,'git',return_value='https://github.com/owner/repo.git'),patch.object(tracker,'sync',return_value={'state':'ok','revision':REV}),patch.object(gp,'GitHub',return_value=self.gh),patch('builtins.print'):
            self.assertEqual(tracker.main(),0)
        self.assertEqual(len(self.gh.sent),1)
        with patch.object(sys,'argv',['tracker','--config',str(config),'publish-status']),patch.object(gp,'GitHub',side_effect=AssertionError('status contacted GitHub')),patch('builtins.print'):
            self.assertEqual(tracker.main(),0)

    def test_opt_in_macos_uses_daily_calendar_without_enabling(self):
        import plistlib
        with patch.object(tracker.platform,'system',return_value='Darwin'):
            result=tracker.scheduler(self.cfg,self.root/'config.json',False)
        value=plistlib.loads((Path(result['files'])/'local.ai-usage.plist').read_bytes())
        self.assertNotIn('StartInterval',value);self.assertEqual(value['StartCalendarInterval'],{'Hour':9,'Minute':0})


class ExportReceiptTests(unittest.TestCase):
    def test_actual_receiver_ack_fixture(self):
        cases=json.loads((ROOT/'tests/fixtures/git-publish-aggregate-acks.json').read_text())
        states=[]
        for case in cases:
            request=case['request'];ack=case['response']
            with self.subTest(request=request,status=case['status']):
                if case['status']!=200 or ack.get('sequence')==request['sequence'] and ack.get('sourceRevision')!=request['sourceRevision']:
                    with self.assertRaises(ValueError):exporter.validate_ack(ack,request['sequence'],request['sourceRevision'])
                else:states.append(exporter.validate_ack(ack,request['sequence'],request['sourceRevision'])['state'])
        self.assertEqual(set(states),gp.DONE)

    def test_ack_strict_matching_and_superseded(self):
        for accepted,seq,rev,state in [(True,12,REV,'applied'),(False,12,REV,'already_applied'),(False,13,NEW,'superseded')]:
            self.assertEqual(exporter.validate_ack(dict(accepted=accepted,sequence=seq,sourceRevision=rev),12,REV)['state'],state)
        for ack in ({'accepted':True},{'accepted':1,'sequence':12,'sourceRevision':REV},{'accepted':True,'sequence':13,'sourceRevision':REV},{'accepted':False,'sequence':11,'sourceRevision':REV},{'accepted':False,'sequence':12,'sourceRevision':NEW}):
            with self.assertRaises(ValueError):exporter.validate_ack(ack,12,REV)

    def test_exporter_cli_only_writes_receipt_after_verified_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);payload=dict(sequence=12,sourceRevision=REV,years=[{'weeks':[]}])
            args=['publish','--worktree',str(path),'--revision',REV,'--sequence','12','--output',str(path/'aggregate.json'),'--receipt',str(path/'receipt.json'),'--send']
            class Response(io.BytesIO):status=200
            with patch.object(sys,'argv',args),patch.object(exporter,'export',return_value=payload),patch.dict(exporter.os.environ,AI_USAGE_INGEST_URL='https://example.invalid/ingest',AI_USAGE_INGEST_KEY='s'*32),patch('builtins.print'):
                with patch.object(exporter.urllib.request,'urlopen',return_value=Response(b'{"accepted":true}')):
                    with self.assertRaises(ValueError):exporter.main()
                self.assertFalse((path/'receipt.json').exists())
                with patch.object(exporter.urllib.request,'urlopen',return_value=Response(json.dumps({'accepted':True,'sequence':12,'sourceRevision':REV}).encode())):exporter.main()
                self.assertEqual(json.loads((path/'receipt.json').read_text()),receipt())

    def test_global_conflict_preflight_before_legacy_year_filter(self):
        cases=json.loads((ROOT/'tests/fixtures/git-publish-identities.json').read_text())
        selected=[c for c in cases if c['name'] in ('same_identity_different_year','same_identity_different_year_reverse','incremental_cross_year_conflict','two_identical_deduplicated')]
        with patch.object(store,'now',return_value=AT),patch.object(exporter,'now',return_value=AT):
            for case in selected:
                with self.subTest(case=case['name']),tempfile.TemporaryDirectory() as tmp:
                    for device,dataset in case['partitions'].items():
                        snapshot={k:dataset[k] for k in ('since','until','records','events')}
                        snapshot.update(schema=1,metrics='usage-v1',device=device)
                        store.publish(dict(worktree=tmp,device=device),snapshot,dict(issues=[],state='observed'))
                        base=Path(tmp)/'devices'/device
                        for task in dataset['tasks']:store.atomic(base/'tasks'/(store.digest([task['project'],task['id']])+'.json'),task)
                        for review in dataset['knowledgeReviews']:store.atomic(base/'knowledge-reviews'/(review['id']+'.json'),review)
                        for kind,folder in [('presentations','task-presentations'),('activities','task-activities')]:
                            for value in dataset[kind]:
                                path=Path(tmp)/folder/(store.digest([value['project'],value['id']])+'.json')
                                prior=store.read(path)
                                if prior is not None:self.assertEqual(prior,value)
                                store.atomic(path,value)
                    if case['state']=='held':
                        with self.assertRaisesRegex(ValueError,'Global identity conflict'):exporter.export(tmp,12,REV)
                    else:self.assertEqual(exporter.export(tmp,12,REV)['years'][0]['weeks'][0]['totals']['responses'],1)

if __name__=='__main__':unittest.main()
