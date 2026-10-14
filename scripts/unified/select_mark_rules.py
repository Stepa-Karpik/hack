"""Choose patch-head thresholds/rule on validation pages; report held-out sets (grading only).

Inputs are eval_mark_patches outputs (old global head + new patch head scores per image).
Truth: generator boxes (val/test cohorts), organizer reference marks (kit, evaluation
only) and eye labels for the realistic test documents (evaluation only).
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

CLASSES = ('signature_present', 'seal_present')


def load_truth(work, kit):
    truth = {}
    for name in ('marks-v1/data', 'unified-data-v2', 'unified-real-marks-v1'):
        for split in ('val', 'test'):
            for line in (work / name / f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
                r = json.loads(line)
                if 'target' in r:
                    labels = {k: bool(r['target']['fields'].get(k)) for k in CLASSES if k in r['target']['fields']}
                else:
                    labels = {'signature_present': bool(r['signature']), 'seal_present': bool(r['seal'])}
                truth[str((work / name / r['image']).resolve()).lower()] = (f'{name}:{split}', labels)
    spec = importlib.util.spec_from_file_location('ev', kit / 'evaluate.py')
    refs = {r['document_id']: r for r in json.loads((kit / 'reference_results.json').read_text(encoding='utf-8'))['documents']}
    for did, ref in refs.items():
        for ext in ('png', 'pdf'):
            path = str((kit / 'documents' / f'{did}.{ext}').resolve()).lower()
            truth[path] = (f'kit:{ext}', {k: ref['fields'][k] for k in CLASSES if k in ref['fields']})
    real = json.loads((work / 'marks-v1/real-docs-labels.json').read_text(encoding='utf-8'))['labels']
    return truth, real


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scores', type=Path, nargs='+', required=True)
    p.add_argument('--work', type=Path, default=Path('work'))
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True, help='Head directory to write thresholds.json into')
    args = p.parse_args()
    truth, real = load_truth(args.work, args.kit)
    rows = []
    for f in args.scores:
        for r in json.loads(f.read_text(encoding='utf-8')):
            key = str(Path(r['image']).resolve()).lower()
            if key in truth:
                group, labels = truth[key]
            else:
                m = re.match(r'(\d\d)_.*?-(\d)\.png$', Path(r['image']).name)
                tag = m[1] if m and m[1] != '06' else (f'06-{m[2]}' if m else None)
                if tag not in real:
                    continue
                group, labels = 'realistic', real[tag]
            rows.append((group, labels, r))

    def decide(r, cls, t, rule):
        new = r['new'][cls]['score'] >= t
        return new or (rule == 'or' and r['old'][cls] >= .5)

    def score(subset, cls, t, rule):
        tp = fp = fn = tn = 0
        for _, labels, r in subset:
            if cls not in labels:
                continue
            pred, true = decide(r, cls, t, rule), labels[cls]
            tp += pred and true; fp += pred and not true; fn += (not pred) and true; tn += (not pred) and not true
        return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'errors': fp + fn}

    val = [x for x in rows if x[0].endswith(':val')]
    chosen = {'thresholds': {}, 'rule': {}}
    for cls in CLASSES:
        best = None
        for rule in ('patch', 'or'):
            for t in [i / 100 for i in range(20, 96, 2)]:
                s = score(val, cls, t, rule)
                key = (s['errors'], s['fp'], rule != 'patch', -t)
                if best is None or key < best[0]:
                    best = (key, t, rule, s)
        chosen['thresholds'][cls] = best[1]
        chosen['rule'][cls] = best[2]
        print(cls, 'chosen on val:', best[1], best[2], best[3])
    groups = sorted({g for g, _, _ in rows})
    report = {'chosen': chosen, 'groups': {}}
    for g in groups:
        subset = [x for x in rows if x[0] == g]
        report['groups'][g] = {cls: {'new': score(subset, cls, chosen['thresholds'][cls], chosen['rule'][cls]),
                                     'old_global_head': score([(a, b, {'old': r['old'], 'new': {c: {'score': 0} for c in CLASSES}}) for a, b, r in subset],
                                                              cls, 1.1, 'or')} for cls in CLASSES}
        print(g, json.dumps({c: (report['groups'][g][c]['old_global_head']['errors'], report['groups'][g][c]['new']['errors']) for c in CLASSES}))
    for g, labels, r in rows:
        if g == 'realistic':
            print('realistic', Path(r['image']).name[:6], labels, {c: (round(r['old'][c], 3), round(r['new'][c]['score'], 3)) for c in CLASSES})
    (args.head / 'thresholds.json').write_text(json.dumps(chosen, indent=1), encoding='utf-8')
    (args.head / 'selection-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
