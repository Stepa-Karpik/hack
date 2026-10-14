"""Post-inference evaluation of fictional geometry/ROI controls, never fitting."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    for name in ['ocr', 'crops', 'evaluation', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    ocr = json.loads(args.ocr.read_text(encoding='utf-8'))
    if not ocr.get('complete') or ocr['task'] != 'ocr':
        raise ValueError('Complete pixel inference required before targets')
    crop = json.loads(args.crops.read_text(encoding='utf-8'))
    expected = json.loads(args.evaluation.read_text(encoding='utf-8'))
    sources = {r['file']: r for r in expected['rows']}
    readings = {r['file']: r for r in ocr['rows']}
    if (len(sources) != 8 or len(crop['rows']) != 8
            or {r['source_image'] for r in crop['rows']} != set(sources)):
        raise ValueError('Exactly eight unique controls required')
    rows = []
    for r in crop['rows']:
        target = sources[r['source_image']]
        if target['sha256'] != r['input_sha256']:
            raise ValueError('Source identity mismatch')
        texts = []
        for c in r['crops']:
            prediction = readings[c['image']]
            if prediction['input_sha256'] != c['sha256']:
                raise ValueError('Crop identity mismatch')
            texts.append(' '.join(prediction['raw'].split()) if not prediction['token_budget_reached'] else None)
        proposal = texts[0] if len(texts) == 2 and texts[0] == texts[1] else None
        exact = proposal == target['printed_target'] if target['printed_target'] else proposal is None
        rows.append({'id': target['id'], 'layout': target['layout'], 'reason': r['reason'],
            'source_sha256': target['sha256'], 'readings': texts, 'consensus': proposal,
            'printed_target': target['printed_target'], 'exact': exact,
            'scope': 'ROI diagnostic only; no application field changed'})
    result = {'scope': 'Eight new fictional viewed geometry controls,4 fonts/4 positive+4 negative. '
            'Same native model, two correlated rereads; not independent evidence or deployed app accuracy. '
            'No training and no participant names in these controls.',
        'exact_controls': sum(r['exact'] for r in rows),
        'positive_consensus': sum(r['consensus'] is not None for r in rows if r['layout'] == 'positive'),
        'negative_proposals': sum(r['consensus'] is not None for r in rows if r['layout'] != 'positive'),
        'source_sha256': {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
                           for name in ['ocr', 'crops', 'evaluation']}, 'rows': rows}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
