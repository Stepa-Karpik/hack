"""Download PaddleOCR-VL 1.6 at the pinned revision and verify every file against the manifest."""
import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
target = Path(sys.argv[2])
target.mkdir(parents=True, exist_ok=True)
for name, meta in manifest['files'].items():
    path = target / name
    if not path.exists() or path.stat().st_size != meta['bytes']:
        hf_hub_download(manifest['repo'], name, revision=manifest['revision'], local_dir=target)
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            digest.update(chunk)
    if digest.hexdigest() != meta['sha256']:
        sys.exit(f'sha256 mismatch: {name}')
    print('ok', name, flush=True)
(target / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
