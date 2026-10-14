"""Offline abstention diagnostics; never change deployed statuses or weights."""
import hashlib
import io
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def region_quality(pages, evidence):
    parts = (evidence or {}).get('parts') or ([evidence] if evidence else [])
    regions = []
    for part in parts:
        box = part.get('bbox')
        page_index = part.get('page', 0)
        if not box or not 0 <= page_index < len(pages):
            continue
        image = pages[page_index]
        left, top = max(0, math.floor(box[0])), max(0, math.floor(box[1]))
        right, bottom = min(image.width, math.ceil(box[2])), min(image.height, math.ceil(box[3]))
        if right <= left or bottom <= top:
            continue
        gray = cv2.cvtColor(np.asarray(image.crop((left, top, right, bottom))), cv2.COLOR_RGB2GRAY)
        regions.append({'height': bottom-top, 'width': right-left,
                        'sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                        'ink_fraction': float(np.mean(gray < 180))})
    return {'regions': regions, 'minimum_height': min((r['height'] for r in regions), default=None),
            'minimum_sharpness': min((r['sharpness'] for r in regions), default=None)}


def evaluate_rule(rows, metric, threshold):
    def rejects(row):
        value = row.get(metric)
        return row['status'] == 'found' and value is not None and value < threshold
    groups = {}
    for condition in sorted({r['condition'] for r in rows}):
        subset = [r for r in rows if r['condition'] == condition]
        groups[condition] = {
            'wrong_rejected': sum(rejects(r) and not r['correct'] for r in subset),
            'correct_found_lost': sum(rejects(r) and r['correct'] for r in subset)}
    wrong = sum(g['wrong_rejected'] for g in groups.values())
    lost = sum(g['correct_found_lost'] for g in groups.values())
    return {'metric': metric, 'threshold': threshold, 'wrong_rejected': wrong,
            'correct_found_lost': lost, 'passes_zero_correct_loss_gate': wrong > 0 and lost == 0,
            'conditions': groups}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from dekanat.pipeline import analyze
    from dekanat.photo_augment import conditions
    from dekanat.extraction import normalize
    from dekanat.schema import SCHEMAS
    rows = []
    analyze((root/'data/demo/study.png').read_bytes(), 'warm.png', retry=True)
    for kind in SCHEMAS:
        truth = json.loads((root/f'data/demo/{kind}.json').read_text(encoding='utf-8'))['fields']
        source = Image.open(root/f'data/demo/{kind}.png').convert('RGB')
        for name, transform in conditions().items():
            buffer = io.BytesIO()
            transform(source).save(buffer, format='PNG')
            pages, result = analyze(buffer.getvalue(), 'camera.png', kind, retry=True)
            for key, expected in truth.items():
                if isinstance(expected, bool):
                    continue
                field = result['fields'][key]
                quality = region_quality(pages, field.get('evidence'))
                rows.append({'type': kind, 'condition': name, 'field': key,
                             'expected': expected, 'value': field['value'], 'status': field['status'],
                             'confidence': field['confidence'],
                             'correct': field['value'] is not None and normalize(str(field['value'])) == normalize(str(expected)),
                             **quality})
            print(kind, name, flush=True)
    trials = [evaluate_rule(rows, metric, threshold) for metric, thresholds in [
        ('confidence', [.6, .65, .7, .75, .8, .85, .9, .95, .98, .99]),
        ('minimum_height', [12, 16, 20, 24, 28, 32]),
        ('minimum_sharpness', [20, 35, 50, 100, 200, 400])] for threshold in thresholds]
    report = {'scope': '399 text fields on 57 previously inspected synthetic camera-like cases, manual type, retry=True. Development calibration only; no independent target-photo accuracy. Raw color rectified evidence regions; metrics depend on font, scale, bbox and content.',
              'runtime_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'dekanat').glob('*.py')},
              'model_sha256': json.loads((root/'artifacts/release_manifest.json').read_text())['model_hashes'],
              'correct': sum(r['correct'] for r in rows),
              'correct_found': sum(r['correct'] and r['status'] == 'found' for r in rows),
              'confident_wrong': sum(not r['correct'] and r['status'] == 'found' for r in rows),
              'trials': trials, 'rows': rows,
              'deployment': 'Diagnostic only. No threshold automatically promoted, even if a development gate passes.'}
    (root/'artifacts/field_abstention.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ['rows', 'trials', 'runtime_sha256', 'model_sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
