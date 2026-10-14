"""Evaluate held-out fictional marks after fitting, never called by trainer."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh grade report required')
    report = json.loads(args.predictions.read_text(encoding='utf-8'))
    if not report['complete']:
        raise ValueError('Complete inference required')
    truth = {split: {r['sha256']: r['target']['fields'] for r in
                    [json.loads(line) for line in (args.data/(split+'.jsonl')).read_text(encoding='utf-8').splitlines()]}
             for split in ('val', 'test')}
    counts = {split: {'documents': 0, 'marks': 0, 'correct': 0, 'false_positive': 0, 'false_negative': 0}
              for split in truth}
    errors = []
    seen = set()
    for row in report['rows']:
        split = row['partition']
        if split not in truth:
            continue
        if row['sha256'] in seen:
            raise ValueError('Duplicate control pixels')
        seen.add(row['sha256'])
        expected = truth[split][row['sha256']]
        counts[split]['documents'] += 1
        for key in ('signature_present', 'seal_present'):
            if key not in expected:
                continue
            actual = row['prediction'][key]
            if type(actual) is not bool or type(expected[key]) is not bool:
                raise ValueError('Boolean output and target required')
            counts[split]['marks'] += 1
            counts[split]['correct'] += actual == expected[key]
            counts[split]['false_positive'] += actual and not expected[key]
            counts[split]['false_negative'] += not actual and expected[key]
            if actual != expected[key]:
                errors.append({'image': row['image'], 'partition': split, 'field': key,
                               'expected': expected[key], 'predicted': actual})
    if any(counts[s]['documents'] != len(truth[s]) for s in truth):
        raise ValueError('Complete fixed control cohorts required')
    result = {'scope': 'Previously viewed fictional expanded val/test, cached features and new readout. '
              'Different split fonts/content, shared renderer and footer conventions; not independent real mark accuracy.',
              'counts': counts, 'errors': errors, 'trained_on_controls': False, 'promoted': False}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
