"""Post-inference API evaluator; publishes only anonymized real-case counts."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    for name in ['predictions', 'controls', 'private_expected', 'output']:
        p.add_argument('--'+name.replace('_', '-'), dest=name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    data = json.loads(args.predictions.read_text(encoding='utf-8'))
    if not data.get('complete') or len(data['rows']) != 9:
        raise ValueError('Complete inference required before answers')
    references = {r['image']: r for r in json.loads(args.controls.read_text(encoding='utf-8'))['records']}
    private = json.loads(args.private_expected.read_text(encoding='utf-8'))['fields']
    counts = {k: 0 for k in ['fields', 'correct_before', 'correct_after', 'lost_correct',
                             'new_correct', 'changed_wrong', 'filled_absent']}
    details = []
    private_summary = None
    for row in data['rows']:
        before = row['before']['fields']
        response = row['response']; after = response['result']['fields']
        changes = response['audit']['prose_recovery']['changes']
        overwritten = [k for k in before if before[k] != 'не найдено' and before[k] != after[k]]
        if overwritten:
            raise ValueError('Previous nonempty value overwritten')
        if row['private']:
            private_summary = {'pages': len(response['document_view']['pages']),
                'added_fields': len(changes), 'literal_matches_prior_confirmed_private_fields':
                    sum(after[c['field']] == private[c['field']] for c in changes),
                'course_not_inferred': after['course'] == 'не найдено',
                'signature_present': after['signature_present'],
                'uncertain_additions': all(response['audit']['bindings'][c['field']]['status'] == 'uncertain'
                    and response['audit']['bindings'][c['field']]['semantic_confidence'] is None for c in changes),
                'input_sha256': row['input_sha256'], 'private_values_not_exported': True}
            continue
        ref = references[row['id']+'.png']
        if row['input_sha256'] != ref['image_sha256']:
            raise ValueError('Control pixel SHA mismatch')
        errors = []
        for key, expected in ref['expected'].items():
            old, new = before[key], after[key]
            a, b = old == expected, new == expected
            counts['fields'] += 1; counts['correct_before'] += a; counts['correct_after'] += b
            counts['lost_correct'] += a and not b; counts['new_correct'] += not a and b
            counts['changed_wrong'] += old != new and not b
            counts['filled_absent'] += expected == 'не найдено' and new != expected
            if not b:
                errors.append({'field': key, 'changed': old != new})
        details.append({'id': row['id'], 'changes': len(changes), 'errors': errors})
    passed = (not counts['lost_correct'] and not counts['changed_wrong'] and not counts['filled_absent']
              and private_summary is not None and private_summary['pages'] == 2
              and private_summary['added_fields'] == private_summary['literal_matches_prior_confirmed_private_fields'] == 6
              and private_summary['signature_present'] and private_summary['course_not_inferred']
              and private_summary['uncertain_additions'] and data['inference_calls'] == 9)
    result = {'scope': 'Fresh whole-upload CPU loopback HTTP,8 viewed fictional controls plus1 previously '
              'confirmed private2page PDF. Not independent real accuracy or single-network improvement.',
        'passed': passed, 'controls': counts, 'details': details, 'private_case': private_summary,
        'inference_calls': data['inference_calls'], 'followup_questions': 18,
        'source_sha256': {k: hashlib.sha256(getattr(args, k).read_bytes()).hexdigest()
                           for k in ['predictions', 'controls', 'private_expected']}}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
