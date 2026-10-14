"""Reproduce the three cohorts underlying 41 metric checks.

Answers are written separately for evaluation, never into the inference manifest.
Existing audit pixels are preserved; generated layouts use the original seeds.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh directory required')
    from dekanat.schema import SCHEMAS
    from dekanat.photo_augment import conditions
    from scripts.evaluate_layouts import example
    args.output.mkdir(parents=True)
    inputs, evaluation = [], []

    def save(identifier, data, kind, cohort, fields, condition=None):
        suffix = '.jpg' if cohort == 'audit' else '.png'
        path = args.output/(identifier.replace('/', '-') + suffix)
        path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        inputs.append({'id': identifier, 'input': str(path), 'sha256': sha, 'document_type': kind})
        evaluation.append({'id': identifier, 'sha256': sha, 'cohort': cohort,
                           'type': kind, 'condition': condition, 'fields': fields})

    records = [json.loads(s) for s in (args.root/'data/audit/annotations.jsonl').read_text(encoding='utf-8').splitlines()]
    records = [r for r in records if 'image' in r][:36]
    if len(records) != 36:
        raise ValueError('36 previous audit images required')
    for r in records:
        data = (args.root/'data'/r['image']).read_bytes()
        save('audit/'+str(r['id']), data, r['type'], 'audit', r['fields'])
    for index, kind in enumerate(SCHEMAS):
        for style in ['columns', 'right_values', 'wrapped']:
            image, truth = example(kind, style, 9900000+index)
            buf = io.BytesIO(); image.save(buf, format='PNG')
            save('layout/'+kind+'/'+style, buf.getvalue(), kind, 'layout', truth, style)
        source_path = args.root/'data/demo'/(kind+'.png')
        source = Image.open(source_path).convert('RGB')
        truth = json.loads((source_path.with_suffix('.json')).read_text(encoding='utf-8'))['fields']
        for condition, transform in conditions().items():
            buf = io.BytesIO(); transform(source).save(buf, format='PNG')
            save('camera/'+kind+'/'+condition, buf.getvalue(), kind, 'camera', truth, condition)
    if len(inputs) != 102:
        raise ValueError('36 audit +9 layout +57 camera required')
    (args.output/'inputs.json').write_text(json.dumps({'inputs': inputs}, indent=2), encoding='utf-8')
    (args.output/'evaluation.json').write_text(json.dumps({'scope': 'Viewed original metric cohorts; answers evaluator-only', 'rows': evaluation}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared 102 inputs without answers; evaluation stored separately')


if __name__ == '__main__':
    main()
