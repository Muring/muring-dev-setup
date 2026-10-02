#!/usr/bin/env python3
"""Synthetic KB integration regressions. Optional MURING_KB_ROOT uses the real CLI."""
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/usage-report/scripts'))
import usage_activity as activity
import usage_knowledge as knowledge
import usage_store as store
import usage_tracker as tracker

CASES = json.loads((ROOT / 'tests/fixtures/ai-task-activity.json').read_text())


def sample(name='knowledge_direct'):
    return copy.deepcopy(next(c['activity'] for c in CASES if c['name'] == name))


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = dict(repo=str(self.root / 'kb'), state=str(self.root / 'state'),
                        worktree=str(self.root / 'data'), device='test', roots=[], projects={})
        self.task = dict(id='task', project='example/app', status='completed', sessions=[], activity=sample())
        self.doc = self.task['activity']['knowledgeDecisions'][0]['document']
        location = Path(self.cfg['repo']) / self.doc
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text('# Synthetic document\n')

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, task=None):
        with patch.object(tracker, 'guard', return_value=Path(self.cfg['worktree'])):
            return tracker.record_task(self.cfg, task or self.task)

    def test_record_selection_is_idempotent_and_private(self):
        self.save()
        events = list((self.root / 'state/kb-events').glob('*.json'))
        self.assertEqual(len(events), 1)
        first = events[0].read_bytes()
        self.save()
        self.assertEqual(first, events[0].read_bytes())
        event = store.read(events[0])
        self.assertEqual(event['project'], self.task['project'])
        self.assertEqual(set(event), {'key', 'kind', 'document', 'project', 'task', 'evidence_kind', 'timestamp'})
        self.assertEqual(store.aggregate(self.cfg['worktree'])['tasks'][0]['activity'], self.task['activity'])

    def test_missing_null_empty_unknown_do_not_infer_selection(self):
        for value in ('missing', None, []):
            task = copy.deepcopy(self.task)
            if value == 'missing':task['activity'].pop('knowledgeDecisions')
            else:task['activity']['knowledgeDecisions'] = value
            self.assertEqual(knowledge.selection_events(self.cfg, task), [])
        task = copy.deepcopy(self.task)
        task['activity']['knowledgeDecisions'][0].update(decision='unknown', evidenceRefs=[])
        self.assertEqual(knowledge.selection_events(self.cfg, task), [])
        with self.assertRaises(ValueError):knowledge.selection_events(self.cfg, task, 'knowledge/other.md')

    def test_sidecar_conflict_rejected_before_replacing_task(self):
        path = Path(self.save())
        key = store.digest([self.task['project'], self.task['id']])
        store.atomic(Path(self.cfg['worktree']) / 'task-activities' / (key + '.json'),
                     dict(version=1, project=self.task['project'], id=self.task['id'], activity=self.task['activity']))
        changed = copy.deepcopy(self.task)
        changed['activity']['knowledgeDecisions'][0]['reason'] = 'Different decision evidence'
        before = path.read_bytes()
        with self.assertRaises(ValueError):self.save(changed)
        self.assertEqual(path.read_bytes(), before)

    def test_search_uses_handle_and_does_not_persist_query_or_selection(self):
        handle = 'a' * 32
        store.atomic(Path(self.cfg['state']) / 'task-runs' / (handle + '.json'), dict(id='task', project='example/app'))
        with patch.object(Path, 'home', return_value=self.root):
            store.atomic(self.root / '.config/ai-workflow/tracking.json', self.cfg)
            with patch.object(knowledge.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{"telemetry":null}')) as run:
                knowledge.search(self.cfg, handle, 'PRIVATE QUERY', True, 3, 'filter')
                command = run.call_args.args[0]
                self.assertEqual(command[command.index('--task-project') + 1], 'example/app')
                self.assertEqual(command[command.index('--task-id') + 1], 'task')
                self.assertEqual(command[command.index('--project') + 1], 'filter')
        text = ''.join(p.read_text() for p in Path(self.cfg['state']).rglob('*.json'))
        self.assertNotIn('PRIVATE QUERY', text)
        self.assertFalse((Path(self.cfg['state']) / 'kb-events').exists())
        with patch.object(Path, 'home', return_value=self.root / 'other'), self.assertRaises(ValueError):
            knowledge.search(self.cfg, handle, 'PRIVATE QUERY')

    def test_finish_retries_failed_review_without_losing_task(self):
        args = SimpleNamespace(id='task', project='example/app', tool='Claude', session_id=None, transcript=None, hook_input=None)
        start = tracker.start_task(self.cfg, args)
        self.assertEqual((start['project'], start['id']), ('example/app', 'task'))
        source = self.root / 'result.json'
        store.atomic(source, self.task)
        with patch.object(tracker, 'guard', return_value=Path(self.cfg['worktree'])), patch.object(knowledge, 'review', side_effect=ValueError('bad history')):
            result = tracker.finish_task(self.cfg, start['handle'], source)
        self.assertEqual(result['knowledgeReview']['state'], 'failed')
        self.assertTrue(Path(result['path']).is_file())
        d = self.task['activity']['knowledgeDecisions'][0]
        expected = dict(schemaVersion=1, visibility='private', recordingRequested=False, inferredApplications=0,
                        rows=[dict(project='example/app', task='task', document=d['document'],
                                   decision=d['decision'], reason=d['reason'], searchLink='direct', state='matched')])
        with patch.object(tracker, 'guard', return_value=Path(self.cfg['worktree'])), patch.object(knowledge, 'review', return_value=expected) as review:
            retried = tracker.finish_task(self.cfg, start['handle'], source)
            self.assertEqual(retried['state'], 'already_finished')
            self.assertEqual(retried['knowledgeReview'], expected)
            self.assertFalse(review.call_args.args[2])

    def test_invalid_contract_never_creates_selection(self):
        for case in CASES:
            if not case['valid'] and case['name'].startswith('knowledge_'):
                bad = dict(self.task, activity=case['activity'])
                with self.subTest(case=case['name']), self.assertRaises(ValueError):self.save(bad)
        self.assertFalse((self.root / 'state/kb-events').exists())


@unittest.skipUnless(os.environ.get('MURING_KB_ROOT'), 'set MURING_KB_ROOT for canonical CLI integration')
class CanonicalIntegrationTests(KnowledgeTests):
    def setUp(self):
        super().setUp()
        self.kb = Path(os.environ['MURING_KB_ROOT'])
        (Path(self.cfg['repo']) / 'scripts').symlink_to(self.kb / 'scripts', target_is_directory=True)

    def test_canonical_schema_and_fixture_parity(self):
        self.assertEqual(activity.SCHEMA, store.read(self.kb / 'contracts/ai-task-activity.schema.json'))
        self.assertEqual(CASES, store.read(self.kb / 'contracts/ai-task-activity-fixtures.json'))
        source = self.root / 'case.json'
        for case in CASES:
            store.atomic(source, {'tasks': [dict(id='example-task', project='example/kb', activity=case['activity'])]})
            result = subprocess.run([sys.executable, str(self.kb / 'scripts/ai_work_records.py'), 'validate', '--input', str(source)], capture_output=True)
            with self.subTest(case=case['name']):self.assertEqual(result.returncode == 0, case['valid'])

    def test_real_search_links_current_handle_without_storing_query(self):
        scripts=Path(self.cfg['repo'])/'scripts'
        scripts.unlink()
        shutil.copytree(self.kb/'scripts',scripts,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(self.kb/'contracts',Path(self.cfg['repo'])/'contracts')
        for folder in ('knowledge','projects','decisions','guides','preferences','inbox','archive/inbox'):
            (Path(self.cfg['repo'])/folder).mkdir(parents=True,exist_ok=True)
        handle='b'*32
        store.atomic(Path(self.cfg['state'])/'task-runs'/(handle+'.json'),dict(project='example/app',id='task'))
        store.atomic(self.root/'.config/ai-workflow/tracking.json',self.cfg)
        with patch.dict(os.environ,{'HOME':str(self.root)}):
            result=knowledge.search(self.cfg,handle,'Synthetic',True)
        key=result['telemetry']['searchId']
        self.assertTrue(result['telemetry']['linked'])
        event=store.read(Path(self.cfg['state'])/'kb-events'/(key+'.json'))
        self.assertEqual((event['project'],event['task']),('example/app','task'))
        self.assertIn(self.doc,[row['document'] for row in event['returned_documents']])
        self.assertNotIn('Synthetic',json.dumps(event))
        self.assertEqual(len(list((Path(self.cfg['state'])/'kb-events').glob('*.json'))),1)

    def test_search_decision_finish_preserves_linked_immutable_attempts(self):
        scripts=Path(self.cfg['repo'])/'scripts'
        scripts.unlink()
        shutil.copytree(self.kb/'scripts',scripts,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(self.kb/'contracts',Path(self.cfg['repo'])/'contracts')
        for folder in ('knowledge','projects','decisions','guides','preferences','inbox','archive/inbox'):
            (Path(self.cfg['repo'])/folder).mkdir(parents=True,exist_ok=True)
        store.atomic(self.root/'.config/ai-workflow/tracking.json',self.cfg)
        args=SimpleNamespace(id='task',project='example/app',tool='Claude',session_id=None,transcript=None,hook_input=None)
        start=tracker.start_task(self.cfg,args)
        with patch.dict(os.environ,{'HOME':str(self.root)}):
            found=knowledge.search(self.cfg,start['handle'],'Synthetic',True)
        search_id=found['telemetry']['searchId']
        decision=self.task['activity']['knowledgeDecisions'][0]
        decision.update(selection='search',searchRefs=[search_id])
        source=self.root/'finish.json';store.atomic(source,self.task)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            saved=tracker.record_task(self.cfg,self.task)
            first=tracker.finish_task(self.cfg,start['handle'],source)
            first_files={p:p.read_bytes() for p in (Path(self.cfg['worktree'])/'devices/test/knowledge-reviews').glob('*.json')}
            second=tracker.finish_task(self.cfg,start['handle'],source)
        for result in (first,second):
            row=result['knowledgeReview']['rows'][0]
            self.assertEqual(row['state'],'missing_application_record')
            self.assertEqual(row['searchLink'],'linked')
        self.assertEqual(store.read(saved)['activity'],self.task['activity'])
        history=store.aggregate(self.cfg['worktree'])['tasks'][0]['knowledgeReviews']
        self.assertEqual(len(history),2)
        self.assertEqual(len({r['id'] for r in history}),2)
        for p,value in first_files.items():self.assertEqual(p.read_bytes(),value)
        selections=[store.read(p) for p in (Path(self.cfg['state'])/'kb-events').glob('*.json') if store.read(p)['kind']=='kb_selection']
        self.assertEqual(len(selections),1)
        self.assertFalse((Path(self.cfg['repo'])/'usage/events').exists())
        self.assertNotIn('Synthetic',''.join(p.read_text() for p in (Path(self.cfg['state'])/'kb-events').glob('*.json')))

    def test_real_review_records_only_confirmed_and_is_idempotent(self):
        before = knowledge.review(self.cfg, [self.task])
        self.assertEqual(before['rows'][0]['state'], 'missing_application_record')
        self.assertFalse((Path(self.cfg['repo']) / 'usage/events').exists())
        recorded = knowledge.review(self.cfg, [self.task], True)
        self.assertEqual(recorded['rows'][0]['state'], 'recorded')
        again = knowledge.review(self.cfg, [self.task], True)
        self.assertEqual(again['rows'][0]['state'], 'matched')
        self.assertEqual(len(list((Path(self.cfg['repo']) / 'usage/events').glob('*.json'))), 1)
        self.assertFalse(list(Path(self.cfg['state']).glob('knowledge-review-*')))

    def test_real_cli_result_is_preserved_through_finished_task_history(self):
        args=SimpleNamespace(id='task',project='example/app',tool='Claude',session_id=None,transcript=None,hook_input=None)
        handle=tracker.start_task(self.cfg,args)['handle']
        source=self.root/'finish.json';store.atomic(source,self.task)
        with patch.object(tracker,'guard',return_value=Path(self.cfg['worktree'])):
            tracker.finish_task(self.cfg,handle,source)
            tracker.review_task(self.cfg,handle,True)
            tracker.review_task(self.cfg,handle)
        task=store.aggregate(self.cfg['worktree'])['tasks'][0]
        self.assertEqual([r['result']['rows'][0]['state'] for r in task['knowledgeReviews']],
                         ['missing_application_record','recorded','matched'])
        self.assertEqual(task['activity'],self.task['activity'])
        self.assertEqual(len({r['id'] for r in task['knowledgeReviews']}),3)

    def test_search_links_missing_broken_and_verified(self):
        decision = self.task['activity']['knowledgeDecisions'][0]
        key = 'a' * 32
        decision.update(selection='search', searchRefs=[key])
        self.assertEqual(knowledge.review(self.cfg, [self.task], True)['rows'][0]['state'], 'search_unavailable')
        event = dict(key=key, kind='kb_search', project='wrong', task='task', returned_documents=[{'document': self.doc}])
        path = Path(self.cfg['state']) / 'kb-events' / (key + '.json')
        store.atomic(path, event)
        self.assertEqual(knowledge.review(self.cfg, [self.task], True)['rows'][0]['state'], 'broken_search_link')
        self.assertFalse((Path(self.cfg['repo']) / 'usage/events').exists())
        event['project'] = self.task['project'];store.atomic(path, event)
        self.assertEqual(knowledge.review(self.cfg, [self.task])['rows'][0]['state'], 'missing_application_record')
        decision.update(decision='reference_only', plannedUse=None, verification=None)
        self.task['activity']['knowledge'] = None
        self.assertEqual(knowledge.review(self.cfg, [self.task], True)['rows'][0]['state'], 'not_applied')
        self.assertFalse((Path(self.cfg['repo']) / 'usage/events').exists())


if __name__ == '__main__':unittest.main()
