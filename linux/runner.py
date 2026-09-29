#!/usr/bin/env python3
"""Run selected steps with real verification, resumable JSONL events and no shell eval."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from lib.config import CATALOG, defaults, validate
from lib.content import ContentStore, GROUPS

ROOT = Path(__file__).resolve().parent


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def environment(config):
    env = dict(os.environ)
    env.update(BOOTSTRAP_CONFIG=json.dumps(config),
               GIT_USER_NAME=config['gitName'], GIT_USER_EMAIL=config['gitEmail'],
               TIMEZONE=config['timezone'], MURING_KB_REPO=config['kbRepo'],
               MURING_KB_DIR=os.path.expanduser(config['kbDir']),
               CONTENT_COMMIT=config['contentCommit'],
               COREPACK_ENABLE_DOWNLOAD_PROMPT='0')
    return env


def execute(config, event_path, step=None, check_only=False, executor=None):
    """executor injection supports tests without installing anything."""
    event_path = Path(event_path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    stop_path = event_path.with_suffix('.stop')
    states = {}
    env = environment(config)

    def event(item, status, message=''):
        states[item] = status
        value = dict(version=1, step=item, status=status, message=message, time=time.time())
        with event_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(f'[{status}] {item}: {message}', flush=True)

    def command(item, mode):
        if executor:
            return executor(item, mode)
        with event_path.with_suffix('.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen(['bash', str(ROOT / 'steps.sh'), mode, item],
                                       env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors='replace')
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
            return process.wait()

    event('_run', 'running')
    try:
        for item in CATALOG:
            identity = item['id']
            if identity not in config['selected']:
                event(identity, 'skipped', '선택하지 않음')
                continue
            if step and identity != step:
                # Inspect dependencies instead of trusting previous run records.
                if identity in config['selected']:
                    event(identity, 'completed' if command(identity, 'check') == 0 else 'pending', '현재 상태 재검사')
                continue
            if stop_path.exists():
                event('_run', 'paused', '현재 단계까지 마쳤습니다. 다시 실행하면 재검사합니다.')
                return 2
            if any(states.get(dep) != 'completed' for dep in item['depends']):
                event(identity, 'pending', '선행 단계 완료 후 재시도하세요.')
                continue
            event(identity, 'running', '현재 상태 확인')
            rc = command(identity, 'check')
            if rc != 0 and not check_only:
                event(identity, 'running', '설치 및 설정 적용')
                rc = command(identity, 'apply')
                if rc == 0:
                    rc = command(identity, 'check')
            if rc == 0:
                event(identity, 'completed', '실제 상태 확인 완료')
            elif rc == 20:
                event(identity, 'action-required', 'Orca 종료 후 재시도하세요. 사용자 지정 명령·지원 버전 안내는 로그를 확인하세요.' if identity == 'orca-codex' else '로그인·앱 설치·브리지 연결 후 재시도하세요.')
            elif rc == 21:
                event(identity, 'reboot-required', 'WSL 재시작 후 재시도하세요.')
            else:
                event(identity, 'failed', '로그를 확인하고 재시도하세요.')
        if not executor and not check_only:
            for identity in config['selected']:
                if states.get(identity) == 'completed' and command(identity, 'check') != 0:
                    event(identity, 'failed', '최종 재검사에서 상태가 변경되었습니다. 재시도하세요.')
        failed = any(states.get(i) != 'completed' for i in config['selected'] if not step or i == step)
        event('_run', 'incomplete' if failed else 'completed', '선택 항목 검증 완료' if not failed else '미완료 항목을 확인하세요.')
        return 1 if failed else 0
    except Exception as error:
        event('_run', 'failed', str(error))
        return 1


def interactive():
    print('개발환경 설치: 1. MuRing (Recommended)  2. 공통 개발환경')
    answer = input('구성 [1]: ').strip()
    if answer not in ('', '1', '2'):
        raise ValueError('1 또는 2를 선택하세요.')
    config = defaults('common' if answer == '2' else 'muring')
    for item in CATALOG:
        if item['required']:
            continue
        if any(dep not in config['selected'] for dep in item['depends']):
            if item['id'] in config['selected']:
                config['selected'].remove(item['id'])
            continue
        chosen = item['id'] in config['selected']
        recommended = item['recommend'] == 'all' or item['recommend'] == config['profile'] or (item['recommend'] == 'zsh' and 'zsh' in config['selected'])
        label = ' — Recommended' if recommended else ''
        print(item['description'])
        answer = input(f'{item["title"]}{label} [{"Y/n" if chosen else "y/N"}]: ').strip().lower()
        if answer not in ('', 'y', 'n'):
            raise ValueError('y 또는 n을 입력하세요.')
        selected = chosen if not answer else answer == 'y'
        if selected and not chosen:
            config['selected'].append(item['id'])
        if not selected and chosen:
            config['selected'].remove(item['id'])
    for item, field, label in [('git-name', 'gitName', 'Git 이름'), ('git-email', 'gitEmail', 'Git 이메일'),
                               ('timezone', 'timezone', '시간대'), ('kb', 'kbRepo', 'KB URL'), ('kb', 'kbDir', 'KB 위치')]:
        if item in config['selected']:
            config[field] = input(f'{label} [{config[field]}]: ').strip() or config[field]
    if any(group in config['selected'] for group in GROUPS):
        preview = ContentStore().preview()
        config['contentCommit'] = preview['commit']
        print(f'GitHub 커맨드·스킬: {preview["commit"]} — {preview["message"]}')
        for change in preview['changes']:
            print(f'  {change["status"]}: {change["path"]}')
    print(json.dumps(config, ensure_ascii=False, indent=2))
    if input('위 설정으로 설치하시겠습니까? [y/N]: ').strip().lower() != 'y':
        raise ValueError('설치를 취소했습니다.')
    return validate(config)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--events', type=Path)
    parser.add_argument('--step', choices=[i['id'] for i in CATALOG])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not args.config and not sys.stdin.isatty():
        parser.error('비대화형 실행에는 --config <JSON 파일>이 필요합니다.')
    config = validate(json.loads(args.config.read_text(encoding='utf-8-sig'))) if args.config else interactive()
    if not args.check and (not args.step or args.step in GROUPS) and any(g in config['selected'] for g in GROUPS) and not config['contentCommit']:
        raise ValueError('커맨드·스킬 미리보기에서 확인한 SHA를 contentCommit에 지정하세요. python3 linux/content.py preview')
    if os.getuid() == 0:
        raise ValueError('root가 아닌 개발 계정에서 실행하세요.')
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"') for line in Path('/etc/os-release').read_text().splitlines()):
        raise ValueError('이 설치기는 Ubuntu만 지원합니다.')
    state = Path.home() / '.local/state/dev-bootstrap'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('다른 설치가 실행 중입니다.')
        # Acquire sudo with the visible terminal before piping step output.
        if not args.check:
            subprocess.run(['sudo', '-v'], check=True)
        atomic_json(state / 'config.json', config)
        return execute(config, args.events or state / 'events.jsonl', args.step, args.check)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
