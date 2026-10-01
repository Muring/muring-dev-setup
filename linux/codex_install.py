#!/usr/bin/env python3
"""Stage verified npm artifacts before replacing the Linux global Codex install."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid

REGISTRY = 'https://registry.npmjs.org/'
PACKAGE = '@openai/codex'


def run(args):
    return subprocess.check_output([str(a) for a in args], text=True, stderr=subprocess.STDOUT, timeout=45).strip()


def target():
    machine = platform.machine()
    if platform.system() != 'Linux' or machine not in ('x86_64', 'aarch64', 'arm64'):
        raise ValueError('지원하는 Linux 플랫폼은 x64와 arm64입니다.')
    arch = 'x64' if machine == 'x86_64' else 'arm64'
    triple = ('x86_64' if arch == 'x64' else 'aarch64') + '-unknown-linux-musl'
    return '@openai/codex-linux-' + arch, triple


def secure_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'registry.npmjs.org' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('npm 공식 HTTPS registry만 허용합니다.')
    return url


class RegistryRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        secure_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, destination):
    # Default HTTPS certificate verification stays enabled, including redirects.
    opener = urllib.request.build_opener(RegistryRedirect())
    with opener.open(secure_url(url), timeout=60) as response, Path(destination).open('wb') as stream:
        secure_url(response.url)
        shutil.copyfileobj(response, stream)


def metadata(name, version, directory):
    dest = directory / ('metadata-' + uuid.uuid4().hex + '.json')
    fetch(REGISTRY + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(version, safe=''), dest)
    data = json.loads(dest.read_text())
    if data.get('name') != name or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', data.get('version', '')):
        raise ValueError('npm 패키지 이름·버전이 일치하지 않습니다.')
    if version != 'latest' and data['version'] != version:
        raise ValueError('요청한 고정 버전과 npm 메타데이터가 다릅니다.')
    return data


def unpack(meta, destination, scratch):
    integrity = meta.get('dist', {}).get('integrity', '')
    if not integrity.startswith('sha512-'):
        raise ValueError('SHA-512 dist.integrity가 필요합니다.')
    expected = base64.b64decode(integrity[7:], validate=True)
    if len(expected) != 64:
        raise ValueError('잘못된 SHA-512 integrity입니다.')
    archive = scratch / (uuid.uuid4().hex + '.tgz')
    fetch(meta['dist']['tarball'], archive)
    with archive.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha512').digest() if hasattr(hashlib, 'file_digest') else None
        if actual is None:
            stream.seek(0); h = hashlib.sha512()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
            actual = h.digest()
    if actual != expected:
        raise ValueError('다운로드 SHA-512 불일치: 기존 설치를 보존합니다.')
    destination.mkdir(parents=True)
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != 'package' or '..' in parts or not (member.isdir() or member.isfile()):
                raise ValueError('허용하지 않는 패키지 경로·링크입니다.')
            out = destination.joinpath(*parts[1:])
            if member.isdir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, out.open('xb') as output:
                    shutil.copyfileobj(source, output)
                out.chmod(0o755 if member.mode & 0o111 else 0o644)
    manifest = json.loads((destination / 'package.json').read_text())
    if manifest.get('name') != meta['name'] or manifest.get('version') != meta['version']:
        raise ValueError('압축 해제한 패키지의 이름·버전이 다릅니다.')


def validate(package, launcher=None, expected=None):
    manifest = json.loads((package / 'package.json').read_text())
    version = manifest['version']
    if manifest.get('name') != PACKAGE or (expected and version != expected):
        raise ValueError('Codex 본체 버전 불일치')
    name, triple = target()
    # Resolve exactly as the npm launcher does, without trusting the npm exit code.
    resolved = run(['node', '-e', 'const {createRequire}=require("module"); console.log(createRequire(process.argv[1]).resolve(process.argv[2]+"/package.json"))',
                    package / 'package.json', name])
    native = Path(resolved).parent
    native_meta = json.loads((native / 'package.json').read_text())
    if native_meta.get('version') != version + '-linux-' + ('x64' if 'x86_64' in triple else 'arm64'):
        raise ValueError('Codex 플랫폼 패키지 버전 불일치')
    binary = native / 'vendor' / triple / 'bin/codex'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Codex 플랫폼 실행 파일이 없거나 실행 불가합니다.')
    with binary.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            raise ValueError('Codex 플랫폼 파일이 ELF 바이너리가 아닙니다.')
    wanted = 'codex-cli ' + version
    for command in ([binary, '--version'], [launcher, '--version'] if launcher else ['node', package / 'bin/codex.js', '--version']):
        if run(command) != wanted:
            raise ValueError('Codex 실행 결과의 버전이 일치하지 않습니다.')
    return version


def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def exists(path):
    return path.exists() or path.is_symlink()


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif exists(path):
        path.unlink()


def recover(journal, package, launcher):
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    backup = package.parent / record['backup']
    if backup.parent != package.parent or not backup.name.startswith('.codex-backup-'):
        raise ValueError('설치 복구 기록이 올바르지 않습니다.')
    if exists(backup):
        remove(package); os.replace(backup, package)
    elif not record['had_package']:
        remove(package)
    if record['old_link'] is None:
        if launcher.is_symlink():
            launcher.unlink()
    else:
        temp = launcher.with_name('.codex-link-' + uuid.uuid4().hex)
        temp.symlink_to(record['old_link']); os.replace(temp, launcher)
    journal.unlink()
    print('이전 Codex 설치를 복원했습니다.', flush=True)


def activate(candidate, package, launcher, version, check_path=False):
    journal = package.parent / '.codex-transaction.json'
    backup = package.parent / ('.codex-backup-' + uuid.uuid4().hex)
    old_link = os.readlink(launcher) if launcher.is_symlink() else None
    if exists(launcher) and (old_link is None or launcher.resolve() != (package / 'bin/codex.js').resolve()):
        raise ValueError('기존 codex 명령이 이 npm 설치 소유가 아닙니다. 덮어쓰지 않습니다.')
    record = dict(backup=backup.name, had_package=exists(package), old_link=old_link)
    write_json(journal, record)
    try:
        if record['had_package']:
            os.replace(package, backup)
        os.replace(candidate, package)
        launcher.parent.mkdir(parents=True, exist_ok=True)
        temp = launcher.with_name('.codex-link-' + uuid.uuid4().hex)
        temp.symlink_to(os.path.relpath(package / 'bin/codex.js', launcher.parent))
        os.replace(temp, launcher)
        validate(package, launcher, version)
        if check_path and run(['codex', '--version']) != 'codex-cli ' + version:
            raise ValueError('PATH에서 실행한 codex 버전이 다릅니다.')
        journal.unlink()
    except BaseException:
        recover(journal, package, launcher)
        raise
    # Retain the previous installation for manual recovery after a successful update.
    return backup if exists(backup) else None


def install(prefix, version='latest', check_path=False):
    if version != 'latest' and not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('버전은 latest 또는 정확한 버전 번호여야 합니다.')
    package = prefix / 'lib/node_modules/@openai/codex'
    launcher = prefix / 'bin/codex'
    package.parent.mkdir(parents=True, exist_ok=True)
    with (package.parent / '.codex-install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover(package.parent / '.codex-transaction.json', package, launcher)
        with tempfile.TemporaryDirectory(prefix='.codex-stage-', dir=package.parent) as temporary:
            scratch = Path(temporary)
            main = metadata(PACKAGE, version, scratch)
            alias, _ = target()
            spec = main.get('optionalDependencies', {}).get(alias, '')
            wanted = 'npm:' + PACKAGE + '@' + main['version'] + '-linux-' + alias.rsplit('-', 1)[1]
            if spec != wanted or main.get('dependencies') or main.get('bin') != {'codex': 'bin/codex.js'}:
                raise ValueError('지원하지 않는 Codex 패키지 구조입니다. 기존 설치를 보존합니다.')
            native = metadata(PACKAGE, spec.removeprefix('npm:' + PACKAGE + '@'), scratch)
            candidate = scratch / 'codex'
            print('Codex ' + main['version'] + ': 본체·플랫폼 패키지 다운로드 및 SHA-512 검증', flush=True)
            unpack(main, candidate, scratch)
            unpack(native, candidate / 'node_modules' / alias, scratch)
            validate(candidate, expected=main['version'])
            backup = activate(candidate, package, launcher, main['version'], check_path)
            print('Codex ' + main['version'] + ' 설치·실행 검증 완료', flush=True)
            if backup:
                print('이전 설치 백업: ' + str(backup), flush=True)
            return main['version']


def main():
    parser = argparse.ArgumentParser(description='검증 후 교체하는 Codex 설치·업데이트')
    parser.add_argument('command', choices=['install', 'check'])
    parser.add_argument('--prefix', type=Path, help='기본값: 현재 npm prefix -g')
    parser.add_argument('--version', default='latest')
    args = parser.parse_args()
    try:
        prefix = (args.prefix or Path(run(['npm', 'prefix', '-g']))).expanduser().resolve()
        selected = shutil.which('codex')
        if not args.prefix and selected and Path(selected).resolve() != (prefix / 'bin/codex').resolve():
            raise ValueError('PATH의 codex가 현재 npm prefix와 다릅니다. 해당 설치를 먼저 확인하세요.')
        if not args.prefix and (prefix / 'bin').resolve() not in [Path(p).resolve() for p in os.environ.get('PATH', '').split(os.pathsep)]:
            raise ValueError('현재 npm prefix의 bin을 PATH에 등록한 뒤 실행하세요.')
        if args.command == 'check':
            package = prefix / 'lib/node_modules/@openai/codex'
            launcher = prefix / 'bin/codex'
            if launcher.resolve() != (package / 'bin/codex.js').resolve():
                raise ValueError('Codex 명령의 npm 연결이 일치하지 않습니다.')
            print(validate(package, launcher))
        else:
            install(prefix, args.version, check_path=not args.prefix)
        return 0
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        print('Codex 검증 실패: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError('설치 중단')
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
