"""Paired grading of image-only OCR runs against v5 synthetic or MWS real targets.

Opened only after both runs completed. Reports whole-page CER on
whitespace-collapsed text, exact lines (v5), and entity-level checks kept
separate from CER: person names, dates, numbers/codes, and invented values in
visibly blank labels. Every changed page is kept for review.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

NAME = re.compile(r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|ична|ич)\b'
                  r'|[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s[А-ЯЁ][а-яё]+')
DATE = re.compile(r'«?\d{1,2}»?\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}'
                  r'|\b\d{1,2}[./]\d{1,2}[./]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b')
CODE = re.compile(r'(?<![\w-])(?:[A-Za-zА-ЯЁа-яё]{0,4}[-/]?\d[\d/.-]*[A-Za-zА-ЯЁа-яё-]*)(?![\w-])')


def norm(text, markdown=False):
    text = unicodedata.normalize('NFC', text or '')
    text = text.replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"').replace('ё', 'е').replace('Ё', 'Е')
    if markdown:
        text = re.sub(r'(?m)^\s*(?:#{1,6}\s*|[=\-]{3,}\s*$)', ' ', text)
        text = re.sub(r'[*|_`]{1,}', ' ', text)
        text = re.sub(r'<[^>]{1,40}>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def distance(a, b):
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def words(text, markdown=False):
    return Counter(re.findall(r'\w+', norm(text, markdown).lower()))


def entities(text):
    t = norm(text)
    return {'names': sorted(set(m.group() for m in NAME.finditer(t))),
            'dates': sorted(set(m.group() for m in DATE.finditer(t))),
            'codes': sorted(set(c for c in CODE.findall(t) if sum(ch.isdigit() for ch in c) >= 3))}


def blank_labels(lines):
    return [re.sub(r'[:\s—-]+$', '', l).strip() for l in lines if re.fullmatch(r'.{3,60}?(?::|\s—)\s*', l)]


def filled_blank(prediction, label):
    for line in prediction.splitlines():
        m = re.match(re.escape(label) + r'\s*(?::|—)\s*(.*)$', line.strip())
        if m and m[1].strip():
            return m[1].strip()
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kind', choices=['v5', 'mws'], required=True)
    p.add_argument('--targets', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--after', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exclude', nargs='*', default=[], help='Inputs excluded for a documented reason (e.g. leakage)')
    args = p.parse_args()
    runs = [json.loads(path.read_text(encoding='utf-8')) for path in (args.before, args.after)]
    if not all(r.get('complete') for r in runs):
        raise ValueError('Both runs must be complete before targets are opened')
    if args.kind == 'v5':
        rows = [json.loads(l) for l in args.targets.read_text(encoding='utf-8').splitlines() if l.strip()]
        targets = {r['image']: r for r in rows}
        key = lambda row: Path(row['path']).name
    else:
        rows = json.loads(args.targets.read_text(encoding='utf-8'))['rows']
        targets = {Path(r['image']).name: {'target_text': r['answer'], 'dataset': r['dataset'], 'sha256': r['sha256']} for r in rows}
        key = lambda row: Path(row['path']).name
    preds = [{key(r): r for r in run['rows'] if key(r) not in args.exclude} for run in runs]
    targets = {k: v for k, v in targets.items() if k not in args.exclude}
    if set(preds[0]) != set(targets) or set(preds[1]) != set(targets):
        raise ValueError('Run membership differs from targets')
    report, totals = [], {'chars': 0, 'edits': [0, 0], 'budget_hits': [0, 0], 'pages_better': 0, 'pages_worse': 0}
    word_totals = {}
    entity_totals = {k: {'total': 0, 'hit': [0, 0], 'lost': 0, 'new': 0} for k in ('names', 'dates', 'codes')}
    line_totals = {'total': 0, 'hit': [0, 0], 'lost': 0, 'new': 0}
    blank_totals = {'labels': 0, 'filled': [0, 0]}
    for name in sorted(targets):
        target = targets[name]
        truth = norm(target['target_text'], markdown=args.kind == 'mws')
        page = {'image': name, 'cer': [], 'budget_hit': []}
        outs = [preds[i][name]['raw'] for i in (0, 1)]
        for i, out in enumerate(outs):
            if preds[i][name].get('token_budget_reached'):
                totals['budget_hits'][i] += 1
            d = distance(norm(out, markdown=args.kind == 'mws'), truth)
            totals['edits'][i] += d
            page['cer'].append(round(d / max(1, len(truth)), 5))
            page['budget_hit'].append(bool(preds[i][name].get('token_budget_reached')))
        totals['chars'] += len(truth)
        truth_words = words(target['target_text'], args.kind == 'mws')
        page['word_hits'] = []
        for i, out in enumerate(outs):
            got = words(out, args.kind == 'mws')
            hit = sum((got & truth_words).values())
            page['word_hits'].append(hit)
            group = word_totals.setdefault(target.get('dataset') or 'all', [[0, 0, 0], [0, 0, 0]])
            group[i][0] += hit; group[i][1] += sum(got.values()); group[i][2] += sum(truth_words.values())
        totals['pages_better'] += page['cer'][1] < page['cer'][0]
        totals['pages_worse'] += page['cer'][1] > page['cer'][0]
        truth_entities = entities(target['target_text'])
        for kind, values in truth_entities.items():
            got = [[v for v in values if v in norm(out)] for out in outs]
            e = entity_totals[kind]
            e['total'] += len(values)
            e['hit'][0] += len(got[0]); e['hit'][1] += len(got[1])
            lost = sorted(set(got[0]) - set(got[1])); new = sorted(set(got[1]) - set(got[0]))
            e['lost'] += len(lost); e['new'] += len(new)
            if lost or new:
                page.setdefault('entity_changes', {})[kind] = {'lost': lost, 'new': new}
        if args.kind == 'v5':
            from scripts.unified.train_natural_v5 import v5_target
            lines = [norm(l) for l in v5_target(target, 'paragraphs').split('\n\n')]
            got = [{norm(l) for l in re.split(r'\n\s*\n|\n', out)} for out in outs]
            flags = [[l in g for l in lines] for g in got]
            line_totals['total'] += len(lines)
            line_totals['hit'][0] += sum(flags[0]); line_totals['hit'][1] += sum(flags[1])
            line_totals['lost'] += sum(a and not b for a, b in zip(*flags))
            line_totals['new'] += sum(b and not a for a, b in zip(*flags))
            for label in blank_labels(target['lines']):
                blank_totals['labels'] += 1
                for i, out in enumerate(outs):
                    value = filled_blank(out, label)
                    if value:
                        blank_totals['filled'][i] += 1
                        page.setdefault('blank_fills', []).append({'run': ['before', 'after'][i], 'label': label, 'value': value})
            page.update(family=target.get('family'), dense=target.get('dense'), degradations=target.get('degradations'))
        else:
            page['dataset'] = target['dataset']
        if page['cer'][0] != page['cer'][1] or 'entity_changes' in page or 'blank_fills' in page:
            page['outputs'] = outs
        report.append(page)
    word_summary = {name: {run: {'precision': round(h / max(1, pr), 5), 'recall': round(h / max(1, t), 5),
                               'f1': round(2 * h / max(1, pr + t), 5)} for run, (h, pr, t) in zip(('before', 'after'), g)}
                    for name, g in word_totals.items()}
    summary = {'kind': args.kind, 'words_order_insensitive': word_summary, 'excluded': args.exclude, 'pages': len(report), 'chars': totals['chars'],
               'cer_before': round(totals['edits'][0] / totals['chars'], 5), 'cer_after': round(totals['edits'][1] / totals['chars'], 5),
               'pages_better': totals['pages_better'], 'pages_worse': totals['pages_worse'],
               'budget_hits': totals['budget_hits'], 'entities': entity_totals,
               'scope': 'v5: original synthetic, held-out font families; mws: real Russian document validation subset (eval only)'}
    if args.kind == 'v5':
        summary['lines'] = line_totals
        summary['blank_labels'] = blank_totals
    else:
        for ds in ('business', 'personal'):
            sel = [r for r in report if r.get('dataset') == ds]
            if sel:
                summary['cer_by_dataset_' + ds] = [round(sum(r['cer'][i] for r in sel) / len(sel), 5) for i in (0, 1)]
    args.output.write_text(json.dumps({'summary': summary, 'pages': report}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
