"""Build-time only: bundle pinned Windows Node and its license in the portable EXE."""
import hashlib
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent / 'orca-auto'
manifest = json.loads((root / 'runtime-manifest.json').read_text())
destination = root / 'runtime'
destination.mkdir(exist_ok=True)
for name, info in manifest['files'].items():
    target = destination / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == info['sha256']:
        continue
    with urllib.request.urlopen(info['url'], timeout=120) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != info['sha256']:
        raise RuntimeError(f'Runtime checksum mismatch: {name}')
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(content)
    temporary.replace(target)
print(f"Verified bundled Windows Node {manifest['version']} and license")
