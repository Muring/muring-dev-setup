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

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        folder=self.root/'devices/device-a';folder.mkdir(parents=True)
        (folder/'manifest.json').write_text(json.dumps({'shards':{'2026-09-07':{},'2026-09-21':{}}}))
        zero={k:0 for k in publish.TOKEN_KEYS};totals={**zero,'input':100,'cache_read':60,'output':20,'responses':1,'total':120,'non_cache_read_input':40}
        self.report=dict(devices=[dict(device='device-a',since='2026-09-01T00:00:00Z',until='2026-09-28T00:00:00Z',health={'PRIVATE':'raw'})],weeks=[dict(week='2026-09-07',period_ended=True,observation='observed',totals=totals,groups=[dict(project='project-a',tool='Codex',model='model',effort='high',**totals)],task_states={'unclassified':totals},diagnostics={k:0 for k in publish.DIAGNOSTIC_KEYS})],tasks=[],quality=dict(problems=[],fallback_identities=0,task_conflicts=0,ambiguous_task_responses=0,comparison='withheld'),field_observation_counts={'cache_read':1},raw='PRIVATE_RAW')
    def tearDown(self):self.tmp.cleanup()
    def run_export(self):
        with patch.object(publish,'aggregate',return_value=self.report),patch.object(publish,'now',return_value=datetime(2026,9,30,tzinfo=timezone.utc)):
            return publish.export(self.root,1,'a'*40)
    def test_allowlist_and_totals(self):
        result=self.run_export();self.assertNotIn('PRIVATE',json.dumps(result));self.assertEqual(result['years'][0]['weeks'][0]['totals']['total'],120)
    def test_gaps_are_unknown(self):
        weeks=self.run_export()['years'][0]['weeks'];self.assertEqual(len(weeks),4);self.assertFalse(weeks[1]['observed']);self.assertTrue(weeks[1]['partial'])
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
