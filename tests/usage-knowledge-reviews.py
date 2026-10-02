#!/usr/bin/env python3
"""Synthetic reconciliation transport/identity/history/privacy regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/usage-report/scripts'))
import usage_knowledge as knowledge
import usage_knowledge_reviews as reviews
import usage_tracker as tracker
import usage_store as store
import usage_publish as publisher

CASES = json.loads((ROOT / 'tests/fixtures/knowledge-reviews.json').read_text())


def sample(name='matched'):
    return copy.deepcopy(next(c for c in CASES if c['name'] == name))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = dict(worktree=str(self.root/'data'), repo=str(self.root/'kb'), state=str(self.root/'state'),
                        device='test', roots=[], projects={})
        self.task = sample()['task']
        self.task.update(sessions=[], verification=[dict(name='Original check',result='pass')])
        self.key = store.digest([self.task['project'],self.task['id']])
        self.task_path = Path(self.cfg['worktree'])/'devices/test/tasks'/(self.key+'.json')
        store.atomic(self.task_path,self.task)

    def tearDown(self):self.tmp.cleanup()

    def test_shared_transport_fixtures(self):
        for case in CASES:
            with self.subTest(case=case['name']):
                if case['valid']:
                    self.assertEqual(reviews.validate(case['review'],case['task']['project'],case['task']['id']),case['review'])
                else:
                    with self.assertRaises(ValueError):reviews.validate(case['review'],case['task']['project'],case['task']['id'])

    def test_source_change_preserves_past_result_without_claiming_current_match(self):
        case=sample('stale_source_preserved');record=case['review']
        self.assertNotEqual(record['sourceDigest'],reviews.fingerprint(case['task']['project'],case['task']['id'],reviews.source_for(case['task'])))
        store.atomic(self.task_path,case['task']);reviews.persist(self.cfg,record)
        saved=store.aggregate(self.cfg['worktree'])['tasks'][0]
        self.assertEqual(saved['activity'],case['task']['activity'])
        self.assertEqual(saved['knowledgeReviews'],[record])
        self.assertNotIn('currentState',saved)

    def test_legacy_missing_review_stays_absent(self):
        task=dict(self.task);task.pop('activity');store.atomic(self.task_path,task)
        self.assertNotIn('knowledgeReviews',store.aggregate(self.cfg['worktree'])['tasks'][0])

    def test_history_limits_identity_and_timezone_order(self):
        first=sample()['review'];second=sample('failed')['review']
        first['reviewedAt']='2026-10-02T10:00:00+09:00'
        second.update(id='b'*32,reviewedAt='2026-10-02T02:00:00Z')
        reviews.persist(self.cfg,second);reviews.persist(self.cfg,first)
        history=store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']
        self.assertEqual([v['id'] for v in history],[first['id'],second['id']])
        for bad in (None,[first,first],[first]*1001):
            with self.assertRaises(ValueError):reviews.validate_reviews(bad,self.task)
        with self.assertRaises(ValueError):reviews.validate(first,'other/project',self.task['id'])

    def test_history_preserves_success_and_later_failure(self):
        first=sample()['review'];second=sample('failed')['review']
        second.update(id='b'*32,reviewedAt='2026-10-02T14:00:00+09:00')
        reviews.persist(self.cfg,first);reviews.persist(self.cfg,second)
        report=store.aggregate(self.cfg['worktree'])
        self.assertEqual([r['status'] for r in report['tasks'][0]['knowledgeReviews']],['completed','failed'])
        self.assertEqual(report['tasks'][0]['verification'],self.task['verification'])
        self.assertEqual(store.read(self.task_path),self.task)
        with self.assertRaises(ValueError):reviews.persist(self.cfg,dict(first,error='tamper'))

    def test_same_id_dedup_conflict_orphan_and_symlink_rejected(self):
        value=sample()['review'];reviews.persist(self.cfg,value)
        other=Path(self.cfg['worktree'])/'devices/other/knowledge-reviews'/(value['id']+'.json')
        store.atomic(other,value)
        self.assertEqual(len(store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']),1)
        changed=copy.deepcopy(value);changed['reviewedAt']='2026-10-02T14:00:00+09:00';store.atomic(other,changed)
        with self.assertRaisesRegex(ValueError,'Conflicting'):store.aggregate(self.cfg['worktree'])
        other.unlink();self.task_path.unlink()
        with self.assertRaisesRegex(ValueError,'target'):store.aggregate(self.cfg['worktree'])
        store.atomic(self.task_path,self.task)
        other.symlink_to(Path(self.cfg['worktree'])/'devices/test/knowledge-reviews'/(value['id']+'.json'))
        with self.assertRaises(ValueError):store.aggregate(self.cfg['worktree'])

    def test_finish_persists_real_result_and_retry_failure_without_overwriting(self):
        args=SimpleNamespace(id=self.task['id'],project=self.task['project'],tool='Claude',session_id=None,transcript=None,hook_input=None)
        handle=tracker.start_task(self.cfg,args)['handle'];source=self.root/'result.json';store.atomic(source,self.task)
        result=sample()['review']['result']
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])), patch.object(knowledge,'review',return_value=result):
            ended=tracker.finish_task(self.cfg,handle,source)
        self.assertEqual(ended['knowledgeReview'],result)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])), patch.object(knowledge,'review',side_effect=ValueError('private error')):
            retried=tracker.finish_task(self.cfg,handle,source)
        self.assertEqual(retried['knowledgeReview']['state'],'failed')
        history=store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']
        self.assertEqual(len(history),2)
        self.assertEqual(history[0]['result'],result)
        self.assertEqual(history[1]['status'],'failed')
        self.assertEqual(history[0]['source'],reviews.source_for(self.task))
        self.assertNotIn('private error',json.dumps(history))

    def test_unavailable_and_malformed_result_are_not_success(self):
        args=SimpleNamespace(id=self.task['id'],project=self.task['project'],tool='Claude',session_id=None,transcript=None,hook_input=None)
        handle=tracker.start_task(self.cfg,args)['handle'];source=self.root/'result.json';store.atomic(source,self.task)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])), patch.object(knowledge,'review',return_value=dict(state='unavailable',visibility='private',reason='CLI absent')):
            tracker.finish_task(self.cfg,handle,source)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])), patch.object(knowledge,'review',return_value={'rows':[]}):
            tracker.review_task(self.cfg,handle)
        history=store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']
        self.assertEqual([r['status'] for r in history],['unavailable','failed'])
        self.assertTrue(all(r['result'] is None for r in history))

    def test_source_presence_and_digest_distinguishes_missing_null_empty(self):
        values=[]
        for mode in ('missing','null','empty'):
            task=copy.deepcopy(self.task)
            if mode=='missing':task['activity'].pop('knowledgeDecisions')
            else:task['activity']['knowledgeDecisions']=None if mode=='null' else []
            source=reviews.source_for(task);reviews.validate_source(source)
            values.append(reviews.fingerprint(task['project'],task['id'],source))
        self.assertEqual(len(set(values)),3)

    def test_private_publisher_real_store_roundtrip_leaves_totals_unchanged(self):
        logs=self.root/'logs';logs.mkdir();self.cfg['roots']=[dict(tool='Codex',path=str(logs))]
        ts=store.now().isoformat()
        rows=[dict(timestamp=ts,type='session_meta',payload=dict(id='synthetic-session',cwd='/synthetic/project')),
              dict(timestamp=ts,type='token_usage_record',payload=dict(response_id='r',usage=dict(input_tokens=10,output_tokens=2)))]
        (logs/'log.jsonl').write_text('\n'.join(map(json.dumps,rows)))
        snapshot,quality=store.scan(self.cfg);store.publish(self.cfg,snapshot,quality)
        before=publisher.export(self.cfg['worktree'],1,'a'*40)
        record=sample()['review'];reviews.persist(self.cfg,record)
        after=publisher.export(self.cfg['worktree'],2,'a'*40)
        self.assertEqual(before['years'][0]['weeks'],after['years'][0]['weeks'])
        delivered=after['years'][0]['tasks'][0]
        self.assertEqual(delivered['knowledgeReviews'],[record])
        self.assertEqual(delivered['activity'],self.task['activity'])
        self.assertNotIn('knowledgeReviews',after)
        self.assertNotIn('knowledgeReviews',delivered['activity'])
        self.assertEqual(delivered['verification'],self.task['verification'])


if __name__=='__main__':unittest.main()
