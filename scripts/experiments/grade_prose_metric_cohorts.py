"""Evaluate completed paired outputs, then cover the 41 original check groups.

No historical GPU score is substituted for a fresh CPU result. Exact identity of
the fields/validation/answers proves no change from this pure postprocessor.
"""
import argparse
import hashlib
import json
from pathlib import Path


def qualify(report, evaluation, plan):
    if report.get('complete') is not True or len(report.get('rows', [])) != 102:
        raise ValueError('Complete 102 inference outputs required before evaluation')
    specs = {r['id']: r for r in evaluation['rows']}
    rows = report['rows']
    if len(specs) != 102 or len({r['id'] for r in rows}) != 102 or set(specs) != {r['id'] for r in rows}:
        raise ValueError('Exactly matched unique cohort identities required')
    grouped = {'audit': [], 'layout': [], 'camera': []}
    for r in rows:
        spec = specs[r['id']]
        if r['input_sha256'] != spec['sha256']:
            raise ValueError('Evaluation input SHA mismatch')
        if r['requested_type'] != spec['type'] or r['before'] is None:
            raise ValueError('Original manual routing and supported result required')
        grouped[spec['cohort']].append((r, spec))
    if [len(grouped[k]) for k in ['audit', 'layout', 'camera']] != [36, 9, 57]:
        raise ValueError('Original cohort counts differ')
    checks = []
    for item in plan['checks']:
        metric = item['metric']
        if item['id'] in {'known_fields', 'known_cards'}:
            selected = grouped['audit']
        elif item['id'] == 'labelled_layouts':
            selected = grouped['layout']
        elif metric.startswith('summary.'):
            condition = metric.split('.')[1]
            selected = [(r, s) for r, s in grouped['camera'] if s['condition'] == condition]
            if len(selected) != 3:
                raise ValueError('Three original manual types per camera condition required')
        else:
            raise ValueError('Unrecognized original metric check')
        checks.append({'id': item['id'], 'original_metric': metric,
            'method': 'Exact fresh paired official fields/validation/answers identity; no substituted historical score',
            'input_count': len(selected), 'passed': all(r['before'] == r['after'] and not r['changes'] for r, _ in selected)})
    if len(checks) != 41:
        raise ValueError('41 original checks required')
    return {'scope': 'Fresh CPU retry=False original manual routes: 36 audit,9 layouts,57 camera. '
            'Current full service before/after pure candidate; not a rerun of historical GPU metrics '
            'and not independent accuracy. Baseline errors are preserved.',
            'passed': all(c['passed'] for c in checks), 'documents': 102,
            'changed_results': sum(r['before'] != r['after'] for r in rows),
            'candidate_changes': sum(len(r['changes']) for r in rows), 'checks': checks}


def main():
    p = argparse.ArgumentParser()
    for key in ['report', 'evaluation', 'plan', 'output']:
        p.add_argument('--'+key, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh qualification output required')
    report = json.loads(args.report.read_text(encoding='utf-8'))
    if not report.get('complete'):
        raise ValueError('Incomplete inference: evaluator answers not opened')
    result = qualify(report, json.loads(args.evaluation.read_text(encoding='utf-8')),
                     json.loads(args.plan.read_text(encoding='utf-8')))
    result['source_sha256'] = {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
                                for name in ['report', 'evaluation', 'plan']}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
