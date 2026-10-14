"""Organizer evaluation after live one-backbone readout inference completes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from scripts.unified.contract import MARKS


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh grade report required')
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    data = load(args.predictions)
    if not data['complete']:
        raise ValueError('Complete live inference required')
    refs = {r['document_id']: r for r in load(args.kit/'reference_results.json')['documents']}
    baseline = {r['document_id']: r for r in load(args.baseline)['documents']}
    identities = {hashlib.sha256((args.kit/r['image']).read_bytes()).hexdigest(): r['document_id']
                  for r in load(args.kit/'documents.json')}
    spec = importlib.util.spec_from_file_location('organizer_grader', args.kit/'evaluate.py')
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    counts = dict(documents=0, type_correct=0, fields=0, correct=0, text=0, correct_text=0,
                  marks=0, correct_marks=0, false_positive_marks=0, false_negative_marks=0,
                  legacy_correct=0, lost_legacy_correct=0, new_correct=0,
                  wrong_nonempty_text=0, filled_absent_text=0, visual_one_pass=0, native_ocr_tokens_identical=0)
    errors = []
    seen = set()
    for row in data['rows']:
        if row['input_sha256'] in seen:
            raise ValueError('Duplicate input in live cohort')
        seen.add(row['input_sha256'])
        did = identities[row['input_sha256']]
        ref = refs[did]
        result = row['result']
        accepted = result is not None and result['document_type'] == ref['document_type']
        counts['documents'] += 1
        counts['type_correct'] += bool(accepted)
        counts['visual_one_pass'] += row['shared_visual_passes'] == 1
        counts['native_ocr_tokens_identical'] += row['tokens_equal_native_ocr'] is True
        for key, expected in ref['fields'].items():
            actual = result['fields'][key] if accepted else '__invalid__'
            good = grader.exact_value(actual, expected)
            previous_good = grader.exact_value(baseline[did]['fields'][key], expected)
            counts['fields'] += 1
            counts['correct'] += good
            counts['legacy_correct'] += previous_good
            counts['lost_legacy_correct'] += previous_good and not good
            counts['new_correct'] += good and not previous_good
            if key in MARKS:
                counts['marks'] += 1
                counts['correct_marks'] += good
                counts['false_positive_marks'] += actual is True and expected is False
                counts['false_negative_marks'] += actual is False and expected is True
            else:
                counts['text'] += 1
                counts['correct_text'] += good
                wrong = accepted and actual != 'не найдено' and not good
                counts['wrong_nonempty_text'] += wrong
                counts['filled_absent_text'] += wrong and expected == 'не найдено'
            if not good:
                errors.append({'document_id': did, 'field': key, 'was_correct_in_baseline': previous_good,
                               'mark_error': key in MARKS, 'returned_nonempty': actual != 'не найдено'})
    report = {'scope': 'Viewed organizer subset, live single shared native encoder, existing OCR decoder '
              'and newly trained frozen-feature mark head. Six images, not independent real accuracy; '
              'no geometry, no CPU qualification, no full legacy gates or deployment.',
              'counts': counts, 'errors': errors, 'promoted': False}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
