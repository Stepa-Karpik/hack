"""Post-inference fullpage literal grading, including blank-field false filling."""
import argparse
import json
from pathlib import Path
from scripts.unified.literal_grade import normalized, distance


def line_flags(target, prediction):
    if prediction.get('token_budget_reached'):
        return [False] * len(target['expected_lines'])
    actual = {normalized(line) for line in prediction['raw'].splitlines()}
    return [normalized(line) in actual for line in target['expected_lines']]


def blank_fills(target, prediction):
    blanks = [normalized(line) for line in target['expected_lines'] if line.rstrip().endswith(':')]
    actual = [normalized(line) for line in prediction['raw'].splitlines()]
    return [label for label in blanks if any(line.startswith(label) and line[len(label):].strip() for line in actual)]


def compare(expected, before, after):
    indexes = []
    for report in [before, after]:
        if not report.get('complete'):
            raise ValueError('Complete inference required before grading')
        index = {r['input_sha256']: r for r in report['rows']}
        if len(index) != len(report['rows']) or set(index) != {r['sha256'] for r in expected}:
            raise ValueError('Source identity mismatch or duplicate SHA')
        indexes.append(index)
    totals = dict(lines=0, before_lines=0, after_lines=0, lost_correct=0, new_correct=0,
                  chars=0, before_edits=0, after_edits=0, before_blank_fills=0, after_blank_fills=0,
                  changed_wrong_pages=0)
    rows = []
    for target in expected:
        b, a = [index[target['sha256']] for index in indexes]
        flags = [line_flags(target, r) for r in [b, a]]
        lost = sum(x and not y for x, y in zip(*flags))
        new = sum(y and not x for x, y in zip(*flags))
        truth = normalized(target['target_text'])
        texts = [normalized(r['raw']) for r in [b, a]]
        edits = [distance(truth, text) for text in texts]
        fills = [blank_fills(target, r) for r in [b, a]]
        totals['lines'] += len(flags[0])
        totals['before_lines'] += sum(flags[0])
        totals['after_lines'] += sum(flags[1])
        totals['lost_correct'] += lost
        totals['new_correct'] += new
        totals['chars'] += len(truth)
        totals['before_edits'] += edits[0]
        totals['after_edits'] += edits[1]
        totals['before_blank_fills'] += len(fills[0])
        totals['after_blank_fills'] += len(fills[1])
        totals['changed_wrong_pages'] += edits[0] > 0 and edits[1] > 0 and texts[0] != texts[1]
        rows.append({'image': target['image'], 'sha256': target['sha256'], 'font': target['font'],
                     'font_size': target['font_size'], 'exact_line_flags': flags,
                     'lost_correct': lost, 'new_correct': new, 'before_edits': edits[0],
                     'after_edits': edits[1], 'blank_fills_before_after': fills,
                     'image_grids_before_after': [r.get('image_grid_thw') for r in [b, a]]})
    totals['before_cer'] = totals['before_edits'] / totals['chars']
    totals['after_cer'] = totals['after_edits'] / totals['chars']
    return {'scope': 'Synthetic development literal lines, not app or independent real accuracy',
            'normalization': 'NFC and intra-line whitespace only for line equality; whole-output CER uses whitespace normalization',
            'blank_field_metric': 'Nonempty suffix after a visibly empty colon label counts as false fill',
            'counts': totals, 'rows': rows, 'promoted': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve previous grading')
    result = {}
    for split in ['val', 'test']:
        expected = [json.loads(line) for line in (args.data / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        one = json.loads((args.run / f'resolution-1mp-{split}.json').read_text(encoding='utf-8'))
        two = json.loads((args.run / f'baseline-{split}.json').read_text(encoding='utf-8'))
        trained = json.loads((args.run / f'trained-{split}.json').read_text(encoding='utf-8'))
        result[split] = {'resolution_only': compare(expected, one, two),
                         'training_matched_2mp': compare(expected, two, trained),
                         'proposal_vs_base_1mp': compare(expected, one, trained)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: {p: v['counts'] for p, v in r.items()} for k, r in result.items()}), flush=True)


if __name__ == '__main__':
    main()
