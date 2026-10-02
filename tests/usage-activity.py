#!/usr/bin/env python3
"""Synthetic canonical activity contract regressions; no private task data."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/usage-report/scripts'))
import usage_activity as activity
CASES=json.loads((ROOT/'tests/fixtures/ai-task-activity.json').read_text())

class ActivityTests(unittest.TestCase):
    def sample(self,name='known_work'):
        return copy.deepcopy(next(c['activity'] for c in CASES if c['name']==name))
    def test_canonical_fixtures(self):
        for case in CASES:
            with self.subTest(name=case['name']):
                if case['valid']:self.assertEqual(activity.validate(case['activity']),case['activity'])
                else:
                    with self.assertRaises(ValueError):activity.validate(case['activity'])
    def test_limits_nonfinite_and_boolean_numbers(self):
        for value in (float('inf'),float('nan'),True):
            a=self.sample('measured_zero');a['effects'][0]['before']=value
            with self.assertRaises(ValueError):activity.validate(a)
        a=self.sample();a['actions']=['작업']*101
        with self.assertRaises(ValueError):activity.validate(a)
        a=self.sample();a['purpose']='가'*2001
        with self.assertRaises(ValueError):activity.validate(a)
    def test_mutation_does_not_change_original(self):
        a=self.sample();out=activity.validate(a);out['actions'].append('다른 결과');self.assertNotEqual(a,out)
    def test_public_status_transition_requires_user_review(self):
        old=self.sample('draft_no_review');new=copy.deepcopy(old);new['publicCase']['status']='rejected'
        activity.validate(new)
        with self.assertRaises(ValueError):activity.validate_transition(old,new)
        new['publicCase']['review']=self.sample('approved_projection')['publicCase']['review']
        activity.validate_transition(old,new)
    def test_unknown_label_date_and_date_precision_preserved(self):
        a=self.sample('label_date_only');self.assertEqual(activity.validate(a)['timing']['precision'],'unknown')
        a=self.sample('verified_date_only');out=activity.validate(a);self.assertIsNone(out['timing']['occurredAt']);self.assertEqual(out['timing']['precision'],'date')

    def test_handoff_endpoint_and_reporter_evidence(self):
        a=self.sample('handoff_dispatch_accepted')
        activity.validate(a,'example/kb','example-task')
        activity.validate(a,'example/app','actual-recipient-task')
        with self.assertRaises(ValueError):activity.validate(a,'example/kb','wrong-task')
        for kind,reporter in [('received','transport'),('cancelled','transport'),('started','user')]:
            b=copy.deepcopy(a);b['handoffs'][0]['events'][0].update(kind=kind,reportedBy=reporter)
            with self.assertRaises(ValueError):activity.validate(b)

    def test_cross_task_handoff_idempotence_and_conflicts(self):
        a=self.sample('handoff_dispatch_accepted')
        sender=dict(project='example/kb',id='example-task',activity=a)
        recipient=dict(project='example/app',id='recipient-task',activity=copy.deepcopy(a))
        # Evidence ids are activity-local; the underlying evidence is identical.
        recipient['activity']['evidence'].append(dict(a['evidence'][0],id='recipient-proof'))
        recipient['activity']['handoffs'][0]['events'][0]['evidenceRefs']=['recipient-proof']
        activity.validate_collection([sender,recipient])
        for field in ('request','event','outcome'):
            b=copy.deepcopy(recipient);h=b['activity']['handoffs'][0]
            if field=='request':h['request']='다른 요청'
            elif field=='event':h['events'][0]['summary']='다른 사건'
            else:
                for ident,kind in [('done','completed'),('failed','failed')]:
                    h['events'].append(dict(h['events'][0],id=ident,kind=kind,reportedBy='recipient',result=dict(summary='확인 결과',artifacts=[],verification=None)))
            with self.subTest(field=field),self.assertRaises(ValueError):activity.validate_collection([sender,b])

    def test_handoff_update_preserves_previous_events_and_headers(self):
        old=self.sample('handoff_dispatch_accepted');new=copy.deepcopy(old)
        new['handoffs'][0]['events'].append(dict(new['handoffs'][0]['events'][0],id='received-1',kind='received',reportedBy='recipient'))
        activity.validate_transition(old,new)
        for mode in ('header','event','evidence','remove'):
            bad=copy.deepcopy(new)
            if mode=='header':bad['handoffs'][0]['request']='변경'
            elif mode=='event':bad['handoffs'][0]['events'][0]['summary']='변경'
            elif mode=='evidence':bad['evidence'][0]['note']='변경'
            else:bad.pop('handoffs')
            with self.subTest(mode=mode),self.assertRaises(ValueError):activity.validate_transition(old,bad)

    def test_knowledge_decision_history_cannot_be_silently_replaced(self):
        old=self.sample('knowledge_direct')
        activity.validate_transition(old,copy.deepcopy(old))
        for mode in ('reason','remove','evidence'):
            new=copy.deepcopy(old)
            if mode=='reason':new['knowledgeDecisions'][0]['reason']='다른 판단'
            elif mode=='remove':new.pop('knowledgeDecisions')
            else:new['evidence'][0]['note']='다른 근거'
            with self.subTest(mode=mode),self.assertRaises(ValueError):activity.validate_transition(old,new)

if __name__=='__main__':unittest.main()
