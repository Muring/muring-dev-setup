"""Local-only metadata inventory and conservative exact-path deletion guards."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import time

CLASSES = {'agent_temp', 'old_build', 'unused_version', 'cache'}
PROTECTED = {'.git', '.hg', '.svn', '.codex', '.claude', '.ssh', '.aws', '.azure',
             'credentials', 'credentials.json', 'auth.json', 'vm_bundles', 'winsxs',
             'installer', 'pagefile.sys', 'swapfile.sys', 'hiberfil.sys'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def protected_name(name):
    lower = name.casefold()
    return lower in PROTECTED or lower == '.env' or lower.startswith('.env.') or lower.endswith(('.vhd', '.vhdx', '.avhdx', '.qcow2', '.vmdk', '.pem', '.key'))


def canonical(path, platform):
    if not isinstance(path, str) or not path or any(c in path for c in '*?[]\x00\n\r'):
        raise ValueError('Use an exact path without wildcards or control characters')
    if platform == 'windows':
        p = PureWindowsPath(path)
        if not re.fullmatch('[A-Za-z]:', p.drive) or not p.is_absolute() or '..' in p.parts:
            raise ValueError('Only absolute local Windows drive paths are supported')
        if any(':' in part or part.endswith((' ', '.')) for part in p.parts[1:]):
            raise ValueError('Windows streams and ambiguous path components are forbidden')
        return str(p).lower()
    p = Path(path).expanduser()
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError('Use an absolute Linux path without parent traversal')
    return str(p)


def inside(path, root, platform, strict=False):
    cls = PureWindowsPath if platform == 'windows' else Path
    p, r = cls(canonical(path, platform)), cls(canonical(root, platform))
    return p.is_relative_to(r) and (not strict or p != r)


def policy_guard(candidate, roots):
    platform = candidate['platform']; path = canonical(candidate['path'], platform)
    if candidate.get('classification') not in CLASSES:
        raise ValueError('Classification is not eligible for cleanup')
    if not any(inside(path, root['path'], platform, strict=True) for root in roots if root['platform'] == platform):
        raise ValueError('Path is outside the configured cleanup roots, or is a root itself')
    parts = (PureWindowsPath(path) if platform == 'windows' else Path(path)).parts
    if any(protected_name(p) for p in parts):
        raise ValueError('Protected data or VM path')
    if platform == 'windows':
        if len(parts) < 4 or parts[1].casefold() in ('windows', 'program files', 'program files (x86)', 'programdata'):
            raise ValueError('Windows system and installation roots are protected')
    else:
        if path in ('/', '/home', '/tmp', str(Path.home())) or any(inside(path, p, 'linux') for p in ('/mnt', '/proc', '/sys', '/dev', '/etc', '/usr', '/bin', '/sbin', '/var/lib', '/boot')):
            raise ValueError('System, mounted Windows or live kernel paths are protected')
        native_linux(path)
        git_guard(path)
    return path


def native_linux(path):
    p = Path(canonical(path, 'linux'))
    if p.is_relative_to('/mnt') or p.resolve().is_relative_to('/mnt'):
        raise ValueError('Use the Windows-native collector for mounted Windows paths')
    result = subprocess.run(['findmnt', '-T', str(p), '-n', '-o', 'FSTYPE'], capture_output=True, text=True, timeout=5)
    if result.returncode or result.stdout.strip().lower() in ('9p', 'drvfs', 'ntfs', 'ntfs3', 'fuseblk', 'cifs', 'smb3', 'virtiofs'):
        raise ValueError('Filesystem is unknown or requires a native collector')


def git_guard(path):
    p = Path(path)
    parent = p.parent
    result = subprocess.run(['git', '-C', str(parent), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=5)
    if result.returncode:
        # A marker above an unreadable/nonstandard repository must not become permission.
        if any((a / '.git').exists() for a in (parent, *parent.parents)):
            raise ValueError('Cannot verify repository ownership')
        return
    repo = Path(result.stdout.strip()); relative = str(p.relative_to(repo))
    tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z', '--', relative], capture_output=True, timeout=5)
    ignored = subprocess.run(['git', '-C', str(repo), 'check-ignore', '-q', '--', relative], timeout=5)
    if tracked.returncode or tracked.stdout or ignored.returncode:
        raise ValueError('Tracked source or uncommitted/non-ignored project files are protected')


@contextmanager
def parent_fd(path):
    p = Path(canonical(path, 'linux'))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        yield fd, p.name
    finally:
        os.close(fd)


def inventory_fd(parent, name, timeout=30):
    started = time.monotonic(); rows = []; seen = set(); logical = allocated = links = 0
    root_stat = os.stat(name, dir_fd=parent, follow_symlinks=False)
    def walk(fd, entry, relative):
        nonlocal logical, allocated, links
        if time.monotonic() - started > timeout:
            raise TimeoutError('Candidate metadata timeout')
        s = os.stat(entry, dir_fd=fd, follow_symlinks=False)
        if s.st_dev != root_stat.st_dev or stat.S_ISLNK(s.st_mode) or not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
            raise ValueError('Reparse/symlink, mount crossing or special file in candidate')
        if protected_name(entry):
            raise ValueError('Protected data inside candidate')
        rows.append([relative, s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_nlink])
        if stat.S_ISDIR(s.st_mode):
            child = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                if os.fstat(child).st_ino != s.st_ino:
                    raise ValueError('Directory changed during inspection')
                for leaf in sorted(os.listdir(child)):
                    walk(child, leaf, relative + '/' + leaf)
                after = os.fstat(child)
                if after.st_mtime_ns != s.st_mtime_ns:
                    raise ValueError('Directory changed during inspection')
            finally:
                os.close(child)
        else:
            if s.st_nlink > 1:
                links += 1
            key = (s.st_dev, s.st_ino)
            if key not in seen:
                seen.add(key); logical += s.st_size; allocated += s.st_blocks * 512
    walk(parent, name, '.')
    return dict(state='complete', logical_bytes=logical, allocated_bytes=allocated, fingerprint=digest(rows),
                modified_epoch=max(r[5] for r in rows) / 1e9, hardlinks=links, files=len(seen), rows=rows)


def inspect_linux(path, timeout=30):
    native_linux(path)
    with parent_fd(path) as (fd, name):
        result = inventory_fd(fd, name, timeout)
    result.pop('rows'); return result


def busy_linux(path):
    target = Path(path)
    if Path.cwd().is_relative_to(target):
        return True
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            links = [process / 'cwd', process / 'exe', *list((process / 'fd').iterdir())]
            for link in links:
                try:
                    value = os.readlink(link).removesuffix(' (deleted)')
                    if value.startswith('/') and Path(value).is_relative_to(target):
                        return True
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except PermissionError:
            raise ValueError('Cannot verify active processes; keep candidate')
    return False


def delete_linux(path, expected, timeout=30):
    """Metadata-checked unlink via anchored directory descriptors, never rmtree."""
    if busy_linux(path):
        raise ValueError('Candidate is used by an active process')
    with parent_fd(path) as (fd, name):
        actual = inventory_fd(fd, name, timeout)
        if actual['fingerprint'] != expected['fingerprint'] or actual['logical_bytes'] != expected['logical_bytes'] or actual['hardlinks']:
            raise ValueError('Candidate changed or has hardlinks')
        indexed = {r[0]: r for r in actual['rows']}
        def erase(parent, entry, relative):
            if relative not in indexed:
                raise ValueError('New entry appeared during apply')
            s = os.stat(entry, dir_fd=parent, follow_symlinks=False); r = indexed[relative]
            if [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_nlink] != r[1:]:
                raise ValueError('Candidate changed during apply')
            if stat.S_ISDIR(s.st_mode):
                child = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    if os.fstat(child).st_ino != s.st_ino:
                        raise ValueError('Directory replaced during apply')
                    for leaf in sorted(os.listdir(child)):
                        erase(child, leaf, relative + '/' + leaf)
                finally:
                    os.close(child)
                final = os.stat(entry, dir_fd=parent, follow_symlinks=False)
                if (final.st_dev, final.st_ino) != (s.st_dev, s.st_ino):
                    raise ValueError('Directory moved during apply')
                os.rmdir(entry, dir_fd=parent)
            else:
                os.unlink(entry, dir_fd=parent)
        erase(fd, name, '.')
