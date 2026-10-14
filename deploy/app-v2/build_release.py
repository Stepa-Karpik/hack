"""Pack the app release (code, web app, small model heads; no base model, data or user documents).

    python deploy/app-v2/build_release.py <out.tar.gz>
"""
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ['scripts', 'dekanat', 'configs', 'web-app', 'deploy/app-v2', 'docs/APP.md', 'docs/ASSISTANT.md', 'LICENSE', 'README.md',
           'models/unified-experimental-graphic-head-fp32-v3', 'models/unified-experimental-natural-v5',
           'models/unified-experimental-mark-patches-v1']
SKIP_DIRS = {'__pycache__', 'experiments'}


def files():
    for item in INCLUDE:
        path = ROOT / item
        if path.is_file():
            yield path
            continue
        for f in sorted(path.rglob('*')):
            if f.is_file() and not SKIP_DIRS & set(f.relative_to(ROOT).parts) and f.suffix not in {'.pyc', '.log'}:
                yield f


def main():
    out = Path(sys.argv[1])
    count = 0
    with tarfile.open(out, 'w:gz') as tar:
        for f in files():
            data = f.read_bytes()
            if f.suffix in {'.sh', '.py', '.service', '.conf', '.txt'}:
                data = data.replace(b'\r\n', b'\n')
            info = tarfile.TarInfo(f.relative_to(ROOT).as_posix())
            info.size, info.mode = len(data), 0o755 if f.suffix == '.sh' else 0o644
            tar.addfile(info, io.BytesIO(data))
            count += 1
    print(out, count, 'files', round(out.stat().st_size / 1e6, 1), 'MB')


if __name__ == '__main__':
    main()
