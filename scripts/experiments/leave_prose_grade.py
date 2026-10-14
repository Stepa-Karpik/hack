"""Separate image-control evaluator; expected fields never reach inference."""
import argparse
import json
from pathlib import Path
from scripts.participantkit.format_v1 import MISSING


def grade(report, manifest, revision):
    if not report['complete']:
        raise ValueError('Partial runs are diagnostic only')
    refs = {r['image']: r for r in manifest['records']}
    counts = {k: 0 for k in ['documents', 'fields', 'correct_before', 'correct_after',
        'correct_present_before', 'correct_present_after', 'lost_correct_present',
        'new_correct_present', 'changed_wrong', 'filled_absent_after']}
    details = []
    for record in report['records']:
        reference = refs[record['image']]
        if reference['image_sha256'] != record['sha256']:
            raise ValueError('Control image SHA mismatch')
        before = record['before']['fields']
        if revision == 'guarded':
            after = record['after']['fields']; changes = record['changes']
        else:
            from scripts.experiments.leave_prose_dates import recover
            audit = record['full_service_audit']
            after, _, changes, _ = recover(before, audit['bindings'], audit['analysis'])
        counts['documents'] += 1
        errors = []
        for key, expected in reference['expected'].items():
            old, new = before[key], after[key]
            good_old, good_new = old == expected, new == expected
            present = expected not in (MISSING, False)
            counts['fields'] += 1
            counts['correct_before'] += good_old; counts['correct_after'] += good_new
            counts['correct_present_before'] += present and good_old
            counts['correct_present_after'] += present and good_new
            counts['lost_correct_present'] += present and good_old and not good_new
            counts['new_correct_present'] += present and good_new and not good_old
            counts['changed_wrong'] += old != new and not good_new
            counts['filled_absent_after'] += expected == MISSING and new != MISSING
            if not good_new:
                errors.append({'field': key, 'expected': expected, 'before': old, 'after': new,
                               'candidate_changed': old != new})
        details.append({'image': record['image'], 'mode': reference['mode'],
                        'changes': changes, 'errors': errors})
    return {'scope': 'Eight viewed fictional image controls; full CPU baseline, deterministic candidate evaluation; not independent real accuracy',
            'revision': revision, 'counts': counts, 'details': details, 'deployed': False,
            'full_legacy_gates_completed': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', choices=['guarded', 'year_abbreviation'], required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    result = grade(json.loads(args.predictions.read_text(encoding='utf-8')),
                   json.loads(args.manifest.read_text(encoding='utf-8')), args.revision)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['counts']))


if __name__ == '__main__':
    main()
