#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/storage-maintenance/scripts'))
import storage
import safety


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='storage-test-');self.root=Path(self.tmp.name)
        self.runtime=patch.object(storage,'activity',return_value=dict(state='inactive',handles='checked'));self.runtime.start();self.addCleanup(self.runtime.stop)
        self.space=patch.object(storage,'free_space',return_value=dict(linux_internal={'free_bytes':100},windows_host=[{'free_bytes':200}]));self.space.start();self.addCleanup(self.space.stop)
        self.candidate=self.root/'old-build';self.candidate.mkdir();(self.candidate/'data').write_bytes(b'hello')
        self.cfg=dict(version=1,timeout_seconds=5,cleanup_roots=[dict(platform='linux',path=str(self.root))],
                      retention=dict(min_age_days=0,keep_latest=0,keep_rollback=0),candidates=[dict(platform='linux',path=str(self.candidate),classification='agent_temp',owner_verified=True,owner_task_completed=True,regenerable_verified=True,provenance='isolated test fixture',recreation_cost='recreate fixture',requires_app_exit=False)])
    def tearDown(self):self.tmp.cleanup()
    def plan(self):return storage.plan(self.cfg)
    def approve(self,plan):
        item=plan['items'][0];m=item['measurement']
        return dict(approved=True,plan_digest=plan['digest'],items=[dict(platform='linux',path=item['path'],fingerprint=m['fingerprint'],logical_bytes=m['logical_bytes'],inactive_confirmed=True)])
    def test_default_dry_run_never_deletes(self):
        p=self.plan();a=self.approve(p)
        self.assertEqual(storage.apply(p)['state'],'dry_run')
        self.assertEqual(storage.apply(p,a)['deleted'],0)
        self.assertEqual((self.candidate/'data').read_bytes(),b'hello')
    def test_execute_requires_exact_approval_and_inactive_confirmation(self):
        p=self.plan();a=self.approve(p)
        with self.assertRaises(ValueError):storage.apply(p,execute=True)
        a['items'][0]['inactive_confirmed']=False
        with self.assertRaisesRegex(ValueError,'Active use'):storage.apply(p,a,True)
        a=self.approve(p);a['items'][0]['path']=str(self.root)
        with self.assertRaises(ValueError):storage.apply(p,a,True)
        self.assertTrue(self.candidate.exists())
    def test_authorized_fixture_deletion(self):
        p=self.plan();a=self.approve(p)
        # Process visibility is an external dependency. Real metadata checks and
        # fd-based unlink still run against our own fixture only.
        with patch.object(safety,'busy_linux',return_value=False):
            self.assertEqual(storage.apply(p,a,True)['state'],'complete')
        self.assertFalse(self.candidate.exists())
    def test_unreadable_process_state_blocks_deletion(self):
        p=self.plan();a=self.approve(p)
        with patch.object(safety,'busy_linux',side_effect=ValueError('unknown process state')):
            self.assertEqual(storage.apply(p,a,True)['state'],'partial')
        self.assertTrue(self.candidate.exists())
    def test_change_after_plan_is_refused(self):
        p=self.plan();a=self.approve(p);(self.candidate/'data').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):storage.apply(p,a,True)
        self.assertTrue(self.candidate.exists())
    def test_old_plan_requires_new_safety_checks(self):
        p=self.plan();p['version']=1;p['digest']=safety.digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaisesRegex(ValueError,'version changed'):storage.apply(p)
    def test_modified_plan_and_expired_plan_refused(self):
        p=self.plan();p['items'][0]['eligible']=False
        with self.assertRaisesRegex(ValueError,'digest'):storage.apply(p)
        p=self.plan();p['expires_at']='2000-01-01T00:00:00+00:00';p['digest']=safety.digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaisesRegex(ValueError,'expired'):storage.apply(p)
    def test_path_escape_symlink_and_protected_content(self):
        outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('keep')
        (self.candidate/'link').symlink_to(outside,target_is_directory=True)
        p=self.plan();self.assertFalse(p['items'][0]['eligible']);self.assertTrue((outside/'keep').exists())
        (self.candidate/'link').unlink();(self.candidate/'.env').write_text('fixture')
        self.assertFalse(self.plan()['items'][0]['eligible'])
        for name in ['swap.vhdx','.claude','.codex','auth.json']:
            c=dict(self.cfg['candidates'][0],path=str(self.root/name))
            with self.assertRaises(ValueError):safety.policy_guard(c,self.cfg['cleanup_roots'])
    def test_parent_symlink_cannot_escape(self):
        alias=self.root/'alias';alias.symlink_to(self.candidate,target_is_directory=True)
        with self.assertRaises(OSError):safety.inspect_linux(str(alias/'data'))
    def test_windows_paths_globs_streams_and_system_roots(self):
        for path in ['C:\\Temp\\*','C:\\Temp\\..\\secret','C:\\Temp\\a:stream','\\\\server\\share\\x','C:\\Temp\\x.']:
            with self.assertRaises(ValueError):safety.canonical(path,'windows')
        c=dict(platform='windows',path='C:\\Windows\\Installer\\file',classification='cache')
        with self.assertRaises(ValueError):safety.policy_guard(c,[dict(platform='windows',path='C:\\')])
    def test_access_failure_is_unknown_not_zero(self):
        with patch.object(storage,'inspect_linux',side_effect=PermissionError('denied')):
            p=self.plan();m=p['items'][0]['measurement']
        self.assertEqual(m['state'],'unknown');self.assertIsNone(m['logical_bytes']);self.assertFalse(p['items'][0]['eligible'])
    def test_timeout_preserves_partial_observations(self):
        with patch.object(storage,'native_linux'),patch.object(storage.subprocess,'run',side_effect=subprocess.TimeoutExpired('du',1,output=b'12\t/tmp/x/sub\n')):
            m=storage.linux_scan('/tmp/x',1)
        self.assertEqual(m['state'],'partial');self.assertIsNone(m['allocated_bytes']);self.assertEqual(m['observed_allocated_bytes'],12)
    def test_hardlink_counts_once_but_blocks_apply(self):
        os.link(self.candidate/'data',self.candidate/'second')
        m=safety.inspect_linux(str(self.candidate));self.assertEqual(m['logical_bytes'],5);self.assertEqual(m['files'],1)
        self.assertFalse(self.plan()['items'][0]['eligible'])
    def test_overlap_does_not_produce_reclaim_sum(self):
        child=self.candidate/'child';child.mkdir()
        self.cfg['candidates'].append(dict(self.cfg['candidates'][0],path=str(child)))
        p=self.plan();self.assertIsNone(p['total_reclaimable_bytes']);self.assertTrue(all(not i['eligible'] for i in p['items']))
    def test_sibling_prefix_is_not_overlap(self):
        other=self.root/'old-build-two';other.mkdir()
        self.cfg['candidates'].append(dict(self.cfg['candidates'][0],path=str(other)))
        p=self.plan();self.assertTrue(all(i['eligible'] for i in p['items']))
    def test_nested_audit_targets_are_nonadditive(self):
        self.cfg['targets']=[dict(platform='linux',path=str(self.candidate)),dict(platform='linux',path=str(self.candidate/'data'))]
        with patch.object(storage,'discovery',return_value={}):result=storage.scan(self.cfg,self.root/'state')
        snapshot=storage.read(result['snapshot']);self.assertIsNone(snapshot['totals']);self.assertEqual(len(snapshot['targets']),2)
    def test_retention_keeps_latest_rollback_and_active(self):
        self.cfg['retention'].update(keep_latest=1,keep_rollback=1)
        for name,rollback,current in [('recent',False,False),('rollback',True,False),('active',False,True)]:
            p=self.root/name;p.mkdir();(p/'artifact').write_text('fixture')
            self.cfg['candidates'].append(dict(self.cfg['candidates'][0],path=str(p),group='releases',rollback=rollback,current=current))
        self.cfg['candidates'][0]['group']='releases'
        p=self.plan();by={Path(i['path']).name:i for i in p['items']}
        self.assertIn('current_version',by['active']['reasons']);self.assertFalse(by['rollback']['eligible'])
        self.assertTrue(any('retained_recent_or_rollback' in i['reasons'] for i in p['items'] if not i.get('rollback')))
    def test_unknown_timestamp_does_not_displace_known_latest(self):
        self.cfg['retention']['keep_latest']=1;self.cfg['candidates'][0]['group']='releases'
        self.cfg['candidates'].append(dict(self.cfg['candidates'][0],path=str(self.root/'missing')))
        p=self.plan();self.assertTrue(all(not i['eligible'] for i in p['items']))
        self.assertIn('retained_recent_or_rollback',p['items'][0]['reasons'])
    def test_git_source_and_untracked_protected_ignored_output_allowed(self):
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        with self.assertRaises(ValueError):safety.git_guard(str(self.candidate))
        (self.root/'.gitignore').write_text('old-build/\n')
        safety.git_guard(str(self.candidate))
        subprocess.run(['git','-C',str(self.root),'add','-f','old-build/data'],check=True)
        with self.assertRaises(ValueError):safety.git_guard(str(self.candidate))
    def test_busy_current_directory_refused(self):
        old=os.getcwd();os.chdir(self.candidate)
        try:self.assertTrue(safety.busy_linux(str(self.candidate)))
        finally:os.chdir(old)
    def test_explicit_preserve_blocks_parent_and_descendant(self):
        self.cfg['preserve']=[dict(platform='linux',path=str(self.candidate/'data'))]
        self.assertIn('explicit_preserve_path',self.plan()['items'][0]['reasons'])
        self.cfg['preserve']=[dict(platform='linux',path=str(self.root),root_only=True)]
        self.assertTrue(self.plan()['items'][0]['eligible'])
    def test_completed_owner_and_regeneration_required(self):
        self.cfg['candidates'][0].update(owner_task_completed=False,regenerable_verified=False)
        reasons=self.plan()['items'][0]['reasons']
        self.assertIn('owner_task_not_completed',reasons);self.assertIn('regeneration_not_verified',reasons)
    def test_unknown_or_active_runtime_held_and_rechecked(self):
        p=self.plan();a=self.approve(p)
        for state in ['unknown','active']:
            with patch.object(storage,'activity',return_value=dict(state=state,handles='unknown')):
                self.assertFalse(self.plan()['items'][0]['eligible'])
                result=storage.apply(p,a,True)
                self.assertEqual(result['results'][0]['state'],'skipped')
                self.assertEqual(result['space_before']['linux_internal']['free_bytes'],100)
                self.assertEqual(result['space_after']['windows_host'][0]['free_bytes'],200)
        self.assertTrue(self.candidate.exists())
    def test_mapped_file_without_open_fd_is_active(self):
        proc=self.root/'proc';task=proc/'123';(task/'fd').mkdir(parents=True)
        (task/'cwd').symlink_to(self.root);(task/'exe').symlink_to('/usr/bin/python3')
        (task/'maps').write_text('100-200 r--p 0000 00:01 123 '+str(self.candidate/'data')+' (deleted)\n')
        self.assertEqual(safety.activity_linux(str(self.candidate),proc_root=proc)['state'],'active')
        (task/'maps').unlink()
        self.assertEqual(safety.activity_linux(str(self.candidate),proc_root=proc)['state'],'unknown')
    def yarn_fixture(self):
        pkg=self.candidate/'v6/npm-example-1-integrity/node_modules/example'
        (pkg/'.bin').mkdir(parents=True);(pkg/'bin').mkdir()
        (pkg/'bin/cli').write_text('fixture executable')
        link=pkg/'.bin/example';link.symlink_to('../bin/cli')
        self.cfg['candidates'][0].update(classification='cache',symlink_policy='yarn-v6-bin')
        return pkg,link
    def test_yarn_internal_link_unlinks_without_following(self):
        pkg,link=self.yarn_fixture()
        p=self.plan();self.assertTrue(p['items'][0]['eligible'])
        with patch.object(safety,'busy_linux',return_value=False):
            self.assertEqual(storage.apply(p,self.approve(p),True)['state'],'complete')
        self.assertFalse(self.candidate.exists())
    def test_yarn_escape_absolute_chained_and_unknown_links_rejected(self):
        pkg,link=self.yarn_fixture();outside=self.root/'outside';outside.write_text('preserve')
        for target in [str(outside),'../../../../../../outside','../bin/chain']:
            link.unlink();link.symlink_to(target)
            chain=pkg/'bin/chain'
            if not chain.is_symlink():chain.symlink_to('cli')
            self.assertFalse(self.plan()['items'][0]['eligible'])
            self.assertEqual(outside.read_text(),'preserve')
        link.unlink();link.symlink_to('../bin/cli')
        (self.candidate/'other-link').symlink_to(outside)
        self.assertFalse(self.plan()['items'][0]['eligible'])
    def test_yarn_link_change_invalidates_manifest(self):
        pkg,link=self.yarn_fixture();p=self.plan();a=self.approve(p)
        (pkg/'bin/other').write_text('changed');link.unlink();link.symlink_to('../bin/other')
        with self.assertRaisesRegex(ValueError,'changed'):storage.apply(p,a,True)
        self.assertTrue(link.is_symlink())
    def test_yarn_package_scope_keeps_protected_data(self):
        pkg,link=self.yarn_fixture()
        self.cfg['candidates'][0]['path']=str(self.candidate/'v6/npm-example-1-integrity')
        self.assertTrue(self.plan()['items'][0]['eligible'])
        (pkg/'.claude').mkdir();(pkg/'.claude/log').write_text('preserve')
        self.assertFalse(self.plan()['items'][0]['eligible'])
        self.assertTrue((pkg/'.claude/log').exists())
    def test_cached_probe_cannot_cover_path_outside_scope(self):
        self.cfg['candidates'][0]['process_probe_scope']=str(self.candidate)
        outside=self.root/'outside';outside.mkdir()
        self.cfg['candidates'].append(dict(self.cfg['candidates'][0],path=str(outside)))
        p=self.plan();self.assertTrue(p['items'][0]['eligible']);self.assertFalse(p['items'][1]['eligible'])
    def test_root_probe_rejects_wrong_namespace_or_failure(self):
        import process_probe
        ident=process_probe.identity(str(self.candidate))
        data=dict(state='inactive',uid=0,path=str(self.candidate),identity=dict(ident,mount_namespace='wrong'))
        with patch.dict(os.environ,WSL_DISTRO_NAME='test'),patch.object(safety.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(data),'')):
            self.assertEqual(safety.activity_linux(str(self.candidate),backend='wsl-root')['state'],'unknown')
        with patch.dict(os.environ,WSL_DISTRO_NAME='test'),patch.object(safety.subprocess,'run',side_effect=subprocess.TimeoutExpired('probe',1)):
            self.assertEqual(safety.activity_linux(str(self.candidate),backend='wsl-root')['state'],'unknown')
    def test_comparison_unknown_and_growth_alerts(self):
        old=dict(measured_at='2026-09-01T00:00:00+00:00',volumes=[],targets=[dict(platform='linux',path='/tmp/x',state='complete',method='du',allocated_bytes=1)])
        new=dict(measured_at='2026-09-08T00:00:00+00:00',volumes=[dict(path='C:\\',free_bytes=1)],targets=[dict(old['targets'][0],allocated_bytes=10*1024**3)])
        a=storage.alerts(new,{},old);self.assertEqual({x['kind'] for x in a},{'low_free_space','rapid_growth'})
        new['targets'][0]['state']='partial'
        self.assertIn('unknown_comparison',{x['kind'] for x in storage.alerts(new,{},old)})
        storage.save(self.root/'snapshot-old.json',old);storage.save(self.root/'snapshot-new.json',new)
        result=storage.compare(self.root,'week',{});self.assertEqual(result['previous'],old['measured_at'])
    def test_bom_and_utf16_decoding(self):
        self.assertEqual(storage.decode('{"a":1}'.encode('utf-16')),'{"a":1}')
        self.assertEqual(storage.decode('{"a":1}'.encode('utf-8-sig')),'{"a":1}')
        self.assertTrue((ROOT/'skills/storage-maintenance/scripts/windows.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))
    def test_schedule_is_proposal_only(self):
        result=subprocess.run([sys.executable,str(storage.SCRIPT),'schedule-plan','--period','week'],capture_output=True,text=True,check=True)
        d=json.loads(result.stdout);self.assertFalse(d['enabled']);self.assertEqual(d['state'],'proposal_only')


if __name__=='__main__':unittest.main()
