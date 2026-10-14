"""Paired organizer-kit field comparison of two completed native runs (grading only).

Uses the organizer evaluator's exact_value. References are opened only after
both runs are complete. Reports lost/new correct fields, changed wrong values,
absent-field fills and marks, separately for PNG and PDF representations.
"""
import argparse
import importlib.util
import json
from pathlib import Path

from scripts.unified.contract import MARKS


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--after', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    runs = [json.loads(path.read_text(encoding='utf-8')) for path in (args.before, args.after)]
    if not all(r['complete'] for r in runs):
        raise ValueError('Complete runs required before references are opened')
    spec = importlib.util.spec_from_file_location('organizer_grader', args.kit / 'evaluate.py')
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    refs = {r['document_id']: r for r in json.loads((args.kit / 'reference_results.json').read_text(encoding='utf-8'))['documents']}
    rows = [{Path(r['file']).name: r for r in run['rows']} for run in runs]
    if set(rows[0]) != set(rows[1]):
        raise ValueError('Different inputs')
    summary, changes = {}, []
    for name in sorted(rows[0]):
        rep = name.rsplit('.', 1)[1]
        did = name.rsplit('.', 1)[0]
        ref = refs[did]
        s = summary.setdefault(rep, {'fields': 0, 'correct': [0, 0], 'text_correct': [0, 0], 'text': 0, 'marks_correct': [0, 0],
                                     'lost': 0, 'new': 0, 'changed_wrong': 0, 'absent_filled': [0, 0]})
        results = []
        for run in rows:
            fields = dict(run[name]['binding']['fields']) if run[name]['binding'].get('document_type') == ref['document_type'] else {}
            for key in MARKS & set(ref['fields']):
                fields[key] = run[name]['graphic_prediction'][key]
            results.append({k: ('не найдено' if fields.get(k) is None else fields[k]) for k in ref['fields']})
        for key, expected in ref['fields'].items():
            good = [evaluator.exact_value(r[key], expected) for r in results]
            s['fields'] += 1
            for i in (0, 1):
                s['correct'][i] += good[i]
                if key in MARKS:
                    s['marks_correct'][i] += good[i]
                else:
                    s['text_correct'][i] += good[i]
                    if expected == 'не найдено' and results[i][key] != 'не найдено':
                        s['absent_filled'][i] += 1
            if key not in MARKS:
                s['text'] += 1
            if good[0] and not good[1]:
                s['lost'] += 1
            if good[1] and not good[0]:
                s['new'] += 1
            if not good[0] and not good[1] and results[0][key] != results[1][key]:
                s['changed_wrong'] += 1
            if results[0][key] != results[1][key]:
                changes.append({'input': name, 'key': key, 'before': results[0][key], 'after': results[1][key],
                                'correct_before_after': good})
    args.output.write_text(json.dumps({'summary': summary, 'changes': changes,
                                       'scope': 'Organizer kit, viewed synthetic development set; evaluation only'},
                                      ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
