#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/usage-report/scripts'))
import usage_publish as publish
import usage_store as store

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        folder=self.root/'devices/device-a';folder.mkdir(parents=True)
        # Hash-valid active inputs for the global preflight; these unit tests
        # continue to inject the aggregate result to isolate projection fields.
        shard=dict(records=[],events=[])
        (folder/'empty.json').write_text(json.dumps(shard))
        entry=dict(path='empty.json',hash=store.digest(shard))
        (folder/'manifest.json').write_text(json.dumps({'schema':1,'metrics':'usage-v1','shards':{'2026-09-07':entry,'2026-09-21':entry}}))
        zero={k:0 for k in publish.TOKEN_KEYS};totals={**zero,'input':100,'cache_read':60,'output':20,'responses':1,'total':120,'non_cache_read_input':40}
        self.report=dict(devices=[dict(device='device-a',since='2026-09-01T00:00:00Z',until='2026-09-28T00:00:00Z',health={'PRIVATE':'raw'})],weeks=[dict(week='2026-09-07',period_ended=True,observation='observed',totals=totals,groups=[dict(project='project-a',tool='Codex',model='model',effort='high',**totals)],task_states={'unclassified':totals},diagnostics={k:0 for k in publish.DIAGNOSTIC_KEYS})],tasks=[],quality=dict(problems=[],fallback_identities=0,task_conflicts=0,ambiguous_task_responses=0,comparison='withheld'),field_observation_counts={'cache_read':1},raw='PRIVATE_RAW')
    def tearDown(self):self.tmp.cleanup()
    def run_export(self):
        with patch.object(publish,'aggregate',return_value=self.report),patch.object(publish,'now',return_value=datetime(2026,9,30,tzinfo=timezone.utc)):
            return publish.export(self.root,1,'a'*40)
    def test_allowlist_and_totals(self):
        result=self.run_export();self.assertNotIn('PRIVATE',json.dumps(result));self.assertEqual(result['years'][0]['weeks'][0]['totals']['total'],120)
    def test_optional_presentation_export_preserves_original_checks(self):
        presentation=dict(title='작업',summary='결과',occurredAt=None,checks=[],followUps=[dict(title='별도 작업',status='delegated',note='위임됨')],knowledge=[],evidence=[])
        task=dict(id='task',project='project-a',type=None,status='completed',verification=[dict(name='원본',result='not_run')],rework=None,conflict=False,totals=self.report['weeks'][0]['totals'])
        self.report['tasks']=[task]
        legacy=self.run_export()['years'][0]['tasks'][0];self.assertNotIn('presentation',legacy)
        task['presentation']=presentation
        new=self.run_export()['years'][0]['tasks'][0];self.assertEqual(new['presentation'],presentation);self.assertEqual(new['verification'],legacy['verification'])
        task['presentation']['extra']='private'
        with self.assertRaises(ValueError):self.run_export()
    def test_activity_private_payload_and_strict_validation(self):
        cases=json.loads((Path(__file__).parent/'fixtures/ai-task-activity.json').read_text());a=next(c['activity'] for c in cases if c['name']=='approved_projection')
        task=dict(id='task',project='project-a',type=None,status='completed',verification=[],rework=None,conflict=False,totals=self.report['weeks'][0]['totals'],activity=a)
        self.report['tasks']=[task];result=self.run_export()
        self.assertEqual(result['years'][0]['tasks'][0]['activity'],a);self.assertNotIn('publicCases',result)
        a['evidence']=[]
        with self.assertRaises(ValueError):self.run_export()
    def test_private_knowledge_decisions_preserved_and_invalid_rejected(self):
        cases=json.loads((Path(__file__).parent/'fixtures/ai-task-activity.json').read_text())
        a=next(c['activity'] for c in cases if c['name']=='knowledge_applied')
        task=dict(id='task',project='project-a',status='completed',conflict=False,totals=self.report['weeks'][0]['totals'],activity=a)
        self.report['tasks']=[task];result=self.run_export()
        self.assertEqual(result['years'][0]['tasks'][0]['activity'],a)
        self.assertNotIn('knowledgeDecisions',result)
        self.assertNotIn('knowledgeDecisions',result['years'][0]['tasks'][0])
        a['knowledgeDecisions'][0]['verification']=None
        with self.assertRaises(ValueError):self.run_export()

    def test_review_publisher_revalidates_private_history(self):
        cases=json.loads((Path(__file__).parent/'fixtures/knowledge-reviews.json').read_text())
        case=next(c for c in cases if c['name']=='matched')
        task=dict(case['task'],conflict=False,totals=self.report['weeks'][0]['totals'],knowledgeReviews=[case['review']])
        self.report['tasks']=[task]
        delivered=self.run_export()['years'][0]['tasks'][0]
        self.assertEqual(delivered['knowledgeReviews'],task['knowledgeReviews'])
        task['knowledgeReviews'][0]['sourceDigest']='0'*64
        with self.assertRaises(ValueError):self.run_export()

    def test_gaps_are_unknown(self):
        weeks=self.run_export()['years'][0]['weeks'];self.assertEqual(len(weeks),4);self.assertFalse(weeks[1]['observed']);self.assertTrue(weeks[1]['partial'])

    def test_private_handoff_payload_and_endpoint_validation(self):
        cases=json.loads((Path(__file__).parent/'fixtures/ai-task-activity.json').read_text())
        a=next(c['activity'] for c in cases if c['name']=='handoff_dispatch_accepted')
        task=dict(id='example-task',project='example/kb',type=None,status='completed',verification=[],rework=None,conflict=False,totals=self.report['weeks'][0]['totals'],activity=a)
        self.report['tasks']=[task]
        result=self.run_export()
        self.assertEqual(result['years'][0]['tasks'][0]['activity']['handoffs'],a['handoffs'])
        self.assertNotIn('handoffs',result)
        task['project']='wrong/project'
        with self.assertRaises(ValueError):self.run_export()
    def test_partial_boundary(self):
        self.report['devices'][0]['since']='2026-09-09T00:00:00Z';self.assertTrue(self.run_export()['years'][0]['weeks'][0]['partial'])
    def test_integrity_failure_preserves_destination(self):
        self.report['quality']['problems']=[dict(code='shard_integrity')]
        with self.assertRaises(ValueError):self.run_export()
    def test_empty_source_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):publish.export(root,1,'a'*40)
    def test_invalid_revision(self):
        with self.assertRaises(ValueError):publish.export(self.root,1,'main')
    def test_snapshot_not_mutated(self):
        before=json.dumps(self.report,sort_keys=True);self.run_export();self.assertEqual(before,json.dumps(self.report,sort_keys=True))
if __name__=='__main__':unittest.main()
