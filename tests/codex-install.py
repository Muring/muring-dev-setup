#!/usr/bin/env python3
"""Exercise staged installs and rollback without changing the user's npm prefix."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_install', ROOT / 'linux/codex_install.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


@unittest.skipUnless(shutil.which('node') and shutil.which('cc'), 'Node and C compiler required')
class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.prefix = self.root / 'prefix'
        self.package = self.prefix / 'lib/node_modules/@openai/codex'
        self.launcher = self.prefix / 'bin/codex'
        self.alias, self.triple = installer.target()
        self.payloads = {}
        self.make_release('1.0.0')
        self.make_release('2.0.0')

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as bundle:
            for name, content, mode in files:
                item = tarfile.TarInfo('package/' + name); item.size = len(content); item.mode = mode
                bundle.addfile(item, io.BytesIO(content))
        return data.getvalue()

    def make_release(self, version, missing=False):
        platform_version = version + '-linux-' + self.alias.rsplit('-', 1)[1]
        manifest = dict(name='@openai/codex', version=version, bin={'codex':'bin/codex.js'},
                        optionalDependencies={self.alias:'npm:@openai/codex@' + platform_version})
        js = ('#!/usr/bin/env node\nconst p=require("path"),{spawnSync}=require("child_process");'
              f'const root=p.dirname(require.resolve("{self.alias}/package.json"));'
              f'const r=spawnSync(p.join(root,"vendor/{self.triple}/bin/codex"),process.argv.slice(2),{{stdio:"inherit"}});'
              'process.exit(r.status===null?1:r.status);\n').encode()
        main = self.archive([('package.json', json.dumps(manifest).encode(), 0o644), ('bin/codex.js', js, 0o755)])
        c = self.root / 'sample.c'; executable = self.root / 'sample'
        c.write_text('#include <stdio.h>\nint main(void){puts("codex-cli ' + version + '");return 0;}')
        subprocess.run(['cc', str(c), '-o', str(executable)], check=True, capture_output=True)
        native_manifest = dict(name='@openai/codex',version=platform_version)
        files=[('package.json',json.dumps(native_manifest).encode(),0o644)]
        if not missing: files.append(('vendor/'+self.triple+'/bin/codex',executable.read_bytes(),0o755))
        for v, archive, meta in [(version,main,manifest),(platform_version,self.archive(files),native_manifest)]:
            url='https://registry.npmjs.org/test-'+v+'.tgz'
            self.payloads[url]=archive
            metadata=dict(meta,dist=dict(tarball=url,integrity='sha512-'+base64.b64encode(hashlib.sha512(archive).digest()).decode()))
            self.payloads['https://registry.npmjs.org/%40openai%2Fcodex/'+v]=json.dumps(metadata).encode()
        self.payloads['https://registry.npmjs.org/%40openai%2Fcodex/latest']=self.payloads['https://registry.npmjs.org/%40openai%2Fcodex/'+version]

    def fetch(self, url, destination):
        installer.secure_url(url)
        Path(destination).write_bytes(self.payloads[url])

    def install(self, version):
        with patch.object(installer,'fetch',side_effect=self.fetch):
            return installer.install(self.prefix,version)

    def assert_old(self):
        self.assertEqual(installer.validate(self.package,self.launcher),'1.0.0')
        self.assertFalse((self.package.parent/'.codex-transaction.json').exists())

    def test_install_update_backup_and_unrelated_package(self):
        other=self.prefix/'lib/node_modules/other/keep';other.parent.mkdir(parents=True);other.write_text('keep')
        self.install('1.0.0');self.install('2.0.0')
        self.assertEqual(installer.validate(self.package,self.launcher),'2.0.0')
        backup=next(self.package.parent.glob('.codex-backup-*'))
        self.assertEqual(installer.validate(backup),'1.0.0')
        self.assertEqual(other.read_text(),'keep')

    def test_missing_optional_binary_preserves_old_install(self):
        self.install('1.0.0');self.make_release('2.0.0',missing=True)
        with self.assertRaisesRegex(ValueError,'플랫폼 실행 파일'):
            self.install('2.0.0')
        self.assert_old()

    def test_download_failure_preserves_old_install(self):
        self.install('1.0.0')
        with patch.object(installer,'fetch',side_effect=OSError('TLS failed')):
            with self.assertRaises(OSError):installer.install(self.prefix,'2.0.0')
        self.assert_old()

    def test_integrity_failure_preserves_old_install(self):
        self.install('1.0.0');self.payloads['https://registry.npmjs.org/test-2.0.0.tgz'] += b'bad'
        with self.assertRaisesRegex(ValueError,'SHA-512 불일치'):self.install('2.0.0')
        self.assert_old()

    def test_post_replacement_failure_restores_package_and_link(self):
        self.install('1.0.0');original=installer.validate
        def fail(package, launcher=None, expected=None):
            if package == self.package and expected == '2.0.0': raise ValueError('post-swap failure')
            return original(package,launcher,expected)
        with patch.object(installer,'validate',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'post-swap'):self.install('2.0.0')
        self.assert_old()

    def test_rename_failure_and_interrupted_transaction_recover(self):
        self.install('1.0.0');replace=installer.os.replace
        def fail(src,dst):
            if Path(src).name == 'codex' and '.codex-stage-' in str(src): raise OSError('rename failure')
            return replace(src,dst)
        with patch.object(installer.os,'replace',side_effect=fail):
            with self.assertRaises(OSError):self.install('2.0.0')
        self.assert_old()
        backup=self.package.parent/'.codex-backup-crash'
        record=dict(backup=backup.name,had_package=True,old_link=os.readlink(self.launcher))
        journal=self.package.parent/'.codex-transaction.json';installer.write_json(journal,record)
        os.replace(self.package,backup);self.package.mkdir();(self.package/'broken').write_text('partial')
        installer.recover(journal,self.package,self.launcher);self.assert_old()

    def test_first_install_failure_leaves_no_broken_command(self):
        original=installer.validate
        def fail(package, launcher=None, expected=None):
            if launcher:raise ValueError('fresh swap failure')
            return original(package,launcher,expected)
        with patch.object(installer,'validate',side_effect=fail):
            with self.assertRaises(ValueError):self.install('1.0.0')
        self.assertFalse(installer.exists(self.launcher));self.assertFalse(self.package.exists())

    def test_foreign_launcher_not_overwritten(self):
        self.launcher.parent.mkdir(parents=True);self.launcher.write_text('foreign')
        with self.assertRaisesRegex(ValueError,'소유가 아닙니다'):self.install('1.0.0')
        self.assertEqual(self.launcher.read_text(),'foreign')

    def test_bad_urls_and_archive_traversal(self):
        for url in ['http://registry.npmjs.org/pkg','https://evil.example/pkg','https://user:pass@registry.npmjs.org/pkg']:
            with self.assertRaises(ValueError):installer.secure_url(url)
        data=self.archive([('../escape',b'bad',0o644)])
        url='https://registry.npmjs.org/traversal';self.payloads[url]=data
        meta=dict(dist=dict(tarball=url,integrity='sha512-'+base64.b64encode(hashlib.sha512(data).digest()).decode()))
        with patch.object(installer,'fetch',side_effect=self.fetch):
            with self.assertRaisesRegex(ValueError,'패키지 경로'):
                installer.unpack(meta,self.root/'bad',self.root)
        self.assertFalse((self.root/'escape').exists())

    def test_public_update_entry_uses_same_installer(self):
        # Exercise the real shell entry and fnm selection without downloading or
        # mutating a global package. Capture only the final Python invocation.
        home=self.root/'home';bin=home/'.local/bin';bin.mkdir(parents=True)
        log=self.root/'invocation'
        (bin/'fnm').write_text('#!/bin/sh\nexit 0\n');(bin/'fnm').chmod(0o755)
        (bin/'python3').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_LOG"\n');(bin/'python3').chmod(0o755)
        env=dict(os.environ,HOME=str(home),TEST_LOG=str(log))
        subprocess.run(['bash',str(ROOT/'linux/update-codex.sh')],env=env,check=True)
        self.assertEqual(log.read_text().splitlines(),[str(ROOT/'linux/codex_install.py'),'install'])
        subprocess.run(['bash',str(ROOT/'linux/steps.sh'),'check','codex'],env=env,check=True)
        self.assertEqual(log.read_text().splitlines(),[str(ROOT/'linux/codex_install.py'),'check'])


if __name__ == '__main__':
    unittest.main()
