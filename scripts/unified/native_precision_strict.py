"""Image-only OCR probe with both TF32 flags disabled explicitly."""
import json
import hashlib
import sys
from pathlib import Path


def main():
    import torch
    from scripts.unified.native_precision_probe import main as probe
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    output = Path(sys.argv[sys.argv.index('--output') + 1])
    base = Path(sys.argv[sys.argv.index('--base') + 1])
    source = json.loads((base / 'source-manifest.json').read_text(encoding='utf-8'))
    actual_sha = hashlib.sha256((base / 'model.safetensors').read_bytes()).hexdigest()
    if source['revision'] != 'c5630abae1d940eafe0697512a0325494b02ab42' or actual_sha != '85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db':
        raise ValueError('Pinned foundation identity mismatch')
    probe()
    report = json.loads(output.read_text(encoding='utf-8'))
    report['cuda_matmul_allow_tf32'] = torch.backends.cuda.matmul.allow_tf32
    report['cudnn_allow_tf32'] = torch.backends.cudnn.allow_tf32
    report['actual_base_weight_sha256'] = actual_sha
    report['scope'] = 'Native OCR outputs; inspect budget flags before fullpage grading. No app/server qualification.'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
