"""Paired organizer evaluation after complete frozen-main + fresh-ROI extension."""
import argparse
import importlib.util
import json
from pathlib import Path

from scripts.unified.contract import MARKS


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh full qualification required')
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    data = load(args.predictions)
    if not data['complete']:
        raise ValueError('Partial inference cannot pass gate')
    refs = {r['document_id']: r for r in load(args.kit/'reference_results.json')['documents']}
    spec = importlib.util.spec_from_file_location('organizer_grader', args.kit/'evaluate.py')
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    output = {}
    for variant in ('image', 'pdf'):
        baseline_path = Path('artifacts')/f'participant_service_v7_{variant}_full.json'
        baseline = {r['document_id']: r for r in load(baseline_path)['documents']}
        rows = [r for r in data['rows'] if r['variant'] == variant]
        if len(rows) != len(refs) or {r['document_id'] for r in rows} != set(refs):
            raise ValueError('Complete unique 30-document cohort required per variant')
        counts = dict(documents=len(rows), accepted=0, fields=0, correct=0, text=0, correct_text=0,
                      marks=0, correct_marks=0, false_positive_marks=0, false_negative_marks=0,
                      lost_legacy_correct=0, new_correct=0, wrong_nonempty_text=0, filled_absent_text=0)
        errors = []
        predictions = []
        for row in rows:
            did = row['document_id']
            ref = refs[did]
            result = row['result']
            accepted = result is not None and result['document_type'] == ref['document_type']
            counts['accepted'] += bool(accepted)
            if accepted:
                predictions.append({k: v for k, v in result.items() if k != 'audit'})
            for key, expected in ref['fields'].items():
                actual = result['fields'][key] if accepted else '__invalid__'
                good = grader.exact_value(actual, expected)
                old_good = grader.exact_value(baseline[did]['fields'][key], expected)
                counts['fields'] += 1
                counts['correct'] += good
                counts['lost_legacy_correct'] += old_good and not good
                counts['new_correct'] += good and not old_good
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
                    errors.append({'document_id': did, 'field': key, 'previously_correct': old_good,
                                   'mark': key in MARKS, 'expected_absent': expected == 'не найдено'})
        metrics = grader.evaluate({'version': '1.0', 'documents': list(refs.values())},
            {'version': '1.0', 'documents': predictions}) if counts['accepted'] == len(refs) else None
        output[variant] = {'counts': counts, 'official_metrics': metrics, 'errors': errors,
                           'paired_admission': counts['lost_legacy_correct'] == 0 and counts['wrong_nonempty_text'] == 0
                           and counts['false_positive_marks'] == 0 and counts['false_negative_marks'] == 0}
    report = {'scope': 'Frozen main shared-backbone outputs plus fresh same-base name ROI GPU BF16 1MP; all30 PNG/all30 PDF of viewed synthetic '
              'development documents, not independent real accuracy. Main OCR/marks not rerun; baseline prior GPU service v7, CPU profile differs.',
              'variants': output, 'promoted': False, 'cpu_and_legacy_gates_pending': True}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({v: output[v]['counts'] for v in output}))


if __name__ == '__main__':
    main()
