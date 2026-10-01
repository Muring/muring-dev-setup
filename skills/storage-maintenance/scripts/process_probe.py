#!/usr/bin/env python3
"""Read-only process reference probe. No cleanup or configuration mutations."""
import json
import os
from pathlib import Path
import sys
import time

def probe(path, timeout=30, proc_root=Path('/proc')):
    """A missing process can race exit; unreadable live state never means idle."""
    target = Path(path); started = time.monotonic(); unknown = False; unreadable = []
    if Path.cwd().is_relative_to(target):
        return dict(state='active', evidence='cwd', handles='active')
    def matches(value):
        value = value.removesuffix(' (deleted)')
        return value.startswith('/') and Path(value).is_relative_to(target)
    try:
        for process in proc_root.iterdir():
            if not process.name.isdigit():
                continue
            if time.monotonic() - started > timeout:
                return dict(state='unknown', reason='process_timeout', handles='unknown')
            try:
                # Other users may hold files too; unreadable processes remain unknown.
                links = [process / 'cwd', process / 'exe', *list((process / 'fd').iterdir())]
                for link in links:
                    try:
                        if matches(os.readlink(link)):
                            return dict(state='active', evidence='cwd_exe_or_fd', handles='active')
                    except FileNotFoundError:
                        pass
                for line in (process / 'maps').read_text().splitlines():
                    fields = line.split(None, 5)
                    if len(fields) == 6 and matches(fields[5]):
                        return dict(state='active', evidence='mapped_file', handles='active')
            except FileNotFoundError:
                if process.exists():
                    unknown = True; unreadable.append(process.name)
            except OSError:
                unknown = True; unreadable.append(process.name)
    except OSError:
        unknown = True
    return dict(state='unknown' if unknown else 'inactive', handles='unknown' if unknown else 'checked',
                unreadable_pids=sorted(set(unreadable))[:20], reason='process_visibility_incomplete' if unknown else 'no_observed_references')


def identity(path):
    s = os.stat(path, follow_symlinks=False)
    return dict(device=s.st_dev, inode=s.st_ino,
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                mount_namespace=os.readlink('/proc/self/ns/mnt'))


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1])
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('Exact absolute target required')
        result = probe(str(path), min(600, max(1, int(sys.argv[2]))))
        result.update(identity=identity(path), uid=os.geteuid(), path=str(path))
        print(json.dumps(result))
    except (OSError, ValueError, IndexError) as e:
        print(json.dumps(dict(state='unknown', reason=str(e), handles='unknown')))
