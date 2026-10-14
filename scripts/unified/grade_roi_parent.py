"""Post-inference paired comparison with the frozen unified parent, evaluator only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    for key in ['kit', 'parent', 'candidate', 'output']:
        p.add_argument('--'+key, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh evaluation required')
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    parent, candidate = load(args.parent), load(args.candidate)
    if not parent['complete'] or not candidate['complete']:
        raise ValueError('Complete inference required before reference')
    references = {r['document_id']: r for r in load(args.kit/'reference_results.json')['documents']}
    spec = importlib.util.spec_from_file_location('official_evaluator', args.kit/'evaluate.py')
    evaluator = importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluator)
    original = {(r['variant'], r['document_id']): r for r in parent['rows']}
    if len(original) != 60 or set(original) != {(r['variant'], r['document_id']) for r in candidate['rows']}:
        raise ValueError('Exactly matched whole60 cohort required')
    counts = {v: {k: 0 for k in ['before_correct', 'after_correct', 'lost_correct', 'new_correct', 'changed_wrong']}
              for v in ['image', 'pdf']}
    details = []
    for row in candidate['rows']:
        old = original[(row['variant'], row['document_id'])]
        if row['input_sha256'] != old['input_sha256']:
            raise ValueError('Upload identity differs')
        c = counts[row['variant']]
        for field, expected in references[row['document_id']]['fields'].items():
            a, b = old['result']['fields'][field], row['result']['fields'][field]
            good_a, good_b = evaluator.exact_value(a, expected), evaluator.exact_value(b, expected)
            c['before_correct'] += good_a; c['after_correct'] += good_b
            c['lost_correct'] += good_a and not good_b; c['new_correct'] += not good_a and good_b
            c['changed_wrong'] += a != b and not good_b
            if a != b:
                details.append({'variant': row['variant'], 'document_id': row['document_id'],
                                'field': field, 'correct_before': good_a, 'correct_after': good_b})
    result = {'scope': 'Viewed same synthetic60 representations, paired actual fields against unified parent. '
            'Reference read evaluator-only after completed inference; no independent accuracy claim.',
        'counts': counts, 'changes': details,
        'passed_no_parent_regression': all(c['lost_correct'] == c['changed_wrong'] == 0 for c in counts.values()),
        'source_sha256': {k: hashlib.sha256(getattr(args, k).read_bytes()).hexdigest() for k in ['parent', 'candidate']}}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
