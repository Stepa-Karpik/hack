"""Calibrate the "Проверьте" threshold on field-level token confidence (grading only).

v4b val/test (synthetic, printed values known) choose the threshold; the
organizer kit (reference read only here) is the held-out check. Reports, for
each threshold, the share of wrong values flagged and correct values flagged.
"""
import argparse
import importlib.util
import json
from pathlib import Path

from scripts.app.pipeline import field_confidence
from scripts.participantkit.format_v1 import iso
from scripts.unified.literal_layout import separate_empty_labels, separate_label_runs
from scripts.unified.prose_binding import recover
from scripts.unified.text_binding import DATES, bind


def fields_with_conf(raw, token_confidence):
    text, _ = separate_empty_labels(raw)
    text, _ = separate_label_runs(text)
    binding = recover(text, bind(text))
    out = {}
    for key, value in binding['fields'].items():
        if value is None or key.endswith('_present'):
            continue
        out[key] = (value, field_confidence(text, binding['audit'].get(key) or {}, token_confidence))
    return binding['document_type'], out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--qualification', type=Path, required=True)
    p.add_argument('--v4b', type=Path, required=True)
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    rows = json.loads(args.qualification.read_text(encoding='utf-8'))['rows']
    truth = {}
    for split in ('val', 'test'):
        for line in (args.v4b / f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            truth[r['image']] = {k: (iso(v) if k in DATES else v) for k, v in r['printed_fields'].items() if v}
    spec = importlib.util.spec_from_file_location('ev', args.kit / 'evaluate.py')
    ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
    refs = {r['document_id']: r for r in json.loads((args.kit / 'reference_results.json').read_text(encoding='utf-8'))['documents']}
    samples = {'v4b': [], 'kit': []}
    for row in rows:
        kind, fields = fields_with_conf(row['raw'], row['token_confidence'])
        if row['set'] in ('val', 'test'):
            t = truth[row['file']]
            for key, (value, conf) in fields.items():
                if key in t:
                    samples['v4b'].append({'file': row['file'], 'key': key, 'conf': conf, 'correct': value == t[key]})
        else:
            ref = refs[row['file'].rsplit('.', 1)[0]]
            for key, (value, conf) in fields.items():
                if key in ref['fields'] and ref['fields'][key] != 'не найдено':
                    samples['kit'].append({'file': row['file'], 'key': key, 'conf': conf,
                                           'correct': bool(ev.exact_value(value, ref['fields'][key]))})
    report = {}
    for name, items in samples.items():
        wrong = [s for s in items if not s['correct']]
        right = [s for s in items if s['correct']]
        table = {}
        for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
            flag = lambda s: s['conf'] is not None and s['conf'] < t
            table[str(t)] = {'wrong_flagged': sum(map(flag, wrong)), 'wrong': len(wrong),
                             'correct_flagged': sum(map(flag, right)), 'correct': len(right)}
        report[name] = {'table': table, 'wrong_examples': [{k: s[k] for k in ('file', 'key', 'conf')} for s in wrong],
                        'no_conf': sum(1 for s in items if s['conf'] is None)}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for name in report:
        print(name, json.dumps(report[name]['table']), 'no_conf', report[name]['no_conf'])
        print(' wrong:', report[name]['wrong_examples'])


if __name__ == '__main__':
    main()
