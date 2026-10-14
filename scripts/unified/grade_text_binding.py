"""Evaluation-only binding diagnostic; reference data never enters bind()."""
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
        raise ValueError('Fresh report required')
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    predictions = load(args.predictions)
    if not predictions['complete']:
        raise ValueError('Completed inference required')
    references = {r['document_id']: r for r in load(args.kit/'reference_results.json')['documents']}
    baseline = {r['document_id']: r for r in load(args.baseline)['documents']}
    # Pixels/paths/IDs are matched here only, after inference has completed.
    inputs = {hashlib.sha256((args.kit/r['image']).read_bytes()).hexdigest(): r['document_id']
              for r in load(args.kit/'documents.json')}
    spec = importlib.util.spec_from_file_location('organizer_grade', args.kit/'evaluate.py')
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    counts = dict(documents=0, type_correct=0, text_fields=0, correct_text=0,
                  legacy_correct_text=0, lost_legacy_correct_text=0, new_correct_text=0,
                  wrong_nonempty_text=0, filled_absent_text=0, graphic_fields_unchecked=0)
    errors = []
    for row in predictions['rows']:
        did = inputs[row['input_sha256']]
        ref = references[did]
        binding = row['binding']
        good_type = binding['document_type'] == ref['document_type']
        counts['documents'] += 1
        counts['type_correct'] += good_type
        for key, expected in ref['fields'].items():
            if key in MARKS:
                counts['graphic_fields_unchecked'] += 1
                continue
            actual = binding['fields'].get(key) if good_type else '__invalid__'
            actual = 'не найдено' if actual is None else actual
            good = grader.exact_value(actual, expected)
            old_good = grader.exact_value(baseline[did]['fields'][key], expected)
            counts['text_fields'] += 1
            counts['correct_text'] += good
            counts['legacy_correct_text'] += old_good
            counts['lost_legacy_correct_text'] += old_good and not good
            counts['new_correct_text'] += good and not old_good
            wrong_present = good_type and actual != 'не найдено' and not good
            counts['wrong_nonempty_text'] += wrong_present
            counts['filled_absent_text'] += wrong_present and expected == 'не найдено'
            if not good:
                errors.append({'document_id': did, 'field': key,
                               'returned_nonempty': wrong_present, 'expected_absent': expected == 'не найдено'})
    report = {'scope': 'Viewed organizer development subset, stored native OCR + pure text binding. '
              'Text-only, graphic marks unchecked, no geometry; not app accuracy or production qualification.',
              'counts': counts, 'errors': errors, 'promoted': False}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
