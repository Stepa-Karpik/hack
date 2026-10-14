"""Post-inference literal evaluator; never imported by training or inference."""
import argparse
import json
from pathlib import Path
from scripts.unified.literal_grade import normalized, distance


def paired(expected, before, after):
    indexes = []
    for report in [before, after]:
        if not report.get('complete'):
            raise ValueError('Both prediction runs must be complete')
        index = {r['input_sha256']: r for r in report['rows']}
        if len(index) != len(report['rows']):
            raise ValueError('Duplicate prediction SHA')
        indexes.append(index)
    if any(set(index) != {r['sha256'] for r in expected} for index in indexes):
        raise ValueError('Expected and predicted source identities differ')
    rows = []
    totals = dict(chars=0, before_edits=0, after_edits=0, before_lines=0,
                  after_lines=0, lines=0, lost_correct=0, new_correct=0)
    for target in expected:
        b, a = [index[target['sha256']] for index in indexes]
        truth = normalized(target['target_text'])
        texts = [normalized(r['raw']) for r in [b, a]]
        flags = [[normalized(line) in text and not r.get('token_budget_reached', False)
                  for line in target['expected_lines']] for text, r in zip(texts, [b, a])]
        lost = sum(x and not y for x, y in zip(*flags))
        new = sum(y and not x for x, y in zip(*flags))
        edits = [distance(truth, text) for text in texts]
        totals['chars'] += len(truth)
        totals['lines'] += len(target['expected_lines'])
        totals['before_edits'] += edits[0]
        totals['after_edits'] += edits[1]
        totals['before_lines'] += sum(flags[0])
        totals['after_lines'] += sum(flags[1])
        totals['lost_correct'] += lost
        totals['new_correct'] += new
        rows.append({'image': target['image'], 'sha256': target['sha256'],
                     'before_edits': edits[0], 'after_edits': edits[1],
                     'lost_correct': lost, 'new_correct': new, 'exact_line_flags': flags,
                     'before_budget': b['token_budget_reached'], 'after_budget': a['token_budget_reached']})
    totals['before_cer'] = totals['before_edits'] / totals['chars']
    totals['after_cer'] = totals['after_edits'] / totals['chars']
    return {'scope': 'Viewed synthetic OCR diagnostic, not independent real or application accuracy',
            'normalization': 'NFC/whitespace only; no name, accent, punctuation or digit correction',
            'literal_metric': 'Complete visible line contained verbatim; whole-output CER penalizes extra text',
            'counts': totals, 'rows': rows, 'promoted': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh grading output required')
    result = {}
    for split in ['val', 'test']:
        expected = [json.loads(line) for line in (args.data / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        before = json.loads((args.run / f'baseline-{split}.json').read_text(encoding='utf-8'))
        after = json.loads((args.run / f'trained-{split}.json').read_text(encoding='utf-8'))
        result[split] = paired(expected, before, after)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v['counts'] for k, v in result.items()}), flush=True)


if __name__ == '__main__':
    main()
