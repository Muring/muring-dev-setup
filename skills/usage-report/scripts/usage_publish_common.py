"""Shared Git publisher primitives; no raw-device delivery dependency."""
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile

from usage_store import TZ


def due_period(at):
    local = at.astimezone(TZ)
    return (local.date() if local.hour >= 9 else (local - timedelta(days=1)).date()).isoformat()


def durable_write(path, value):
    """File fsync + atomic rename + directory fsync on platforms that support it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check_global_identities(datasets):
    """Shared preflight for current verified shards or normalized partitions."""
    seen={kind:{} for kind in ('records','events')}
    for dataset in datasets:
        for kind in seen:
            for row in dataset[kind]:
                previous=seen[kind].get(row['key'])
                if previous is not None and previous!=row:raise ValueError('Global identity conflict; retain last good projection')
                seen[kind][row['key']]=row
