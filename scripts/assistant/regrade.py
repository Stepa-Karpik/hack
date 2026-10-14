"""Regrade stored dialogue runs with the current grader (no model calls)."""
import argparse
import json
from datetime import date
from pathlib import Path

from scripts.assistant.benchmark import grade
from scripts.assistant.eval_set import build, stored_contexts


def main():
    p = argparse.ArgumentParser()
    p.add_argument('runs', type=Path, nargs='+')
    p.add_argument('--stored', default='work/unified-literal-values-fp32-lora-v4/kit60.json')
    p.add_argument('--only-ids-from', type=Path, help='Restrict to dialog ids present in this run (paired subset)')
    args = p.parse_args()
    contexts = {c['doc']: c for c in stored_contexts(args.stored)}
    expected = {d['id']: d for d in build(list(contexts.values()))}
    subset = None
    if args.only_ids_from:
        subset = {json.loads(l)['id'] for l in args.only_ids_from.read_text(encoding='utf-8').splitlines() if l.strip()}
    for run in args.runs:
        rows = [json.loads(l) for l in run.read_text(encoding='utf-8').splitlines() if l.strip()]
        if subset is not None:
            rows = [r for r in rows if r['id'] in subset]
        ok = total = seconds = 0
        per = {}
        for r in rows:
            ctx = contexts[r['id'].split(':')[0]]
            for turn, stored in zip(expected[r['id']]['turns'], r['turns']):
                checks = grade(turn, stored['reply'], ctx['result'], ctx['ocr_text'], date(2026, 10, 14))
                good = all(checks.values())
                ok += good
                total += 1
                seconds += stored['wall_seconds']
                cat = r['id'].split(':')[1]
                per.setdefault(cat, [0, 0])
                per[cat][0] += good
                per[cat][1] += 1
        print(json.dumps({'run': run.name, 'dialogs': len(rows), 'turns': total, 'ok': ok,
                          'rate': round(ok / max(1, total), 4), 'mean_s': round(seconds / max(1, total), 2),
                          'by_category': per}, ensure_ascii=False))


if __name__ == '__main__':
    main()
