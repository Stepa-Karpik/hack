"""Post-inference paired literal and schema-value diagnostics, never inference."""
import argparse
import json
from pathlib import Path

from scripts.participantkit.format_v1 import iso
from scripts.unified.grade_literal_fullpage import compare
from scripts.unified.literal_grade import normalized
from scripts.unified.prepare_literal_training import sha
from scripts.unified.text_binding import bind, DATES


def values(expected, before, after):
    indexes = [{r['input_sha256']: r for r in report['rows']} for report in [before, after]]
    totals = dict(present=0, blank=0, before_correct=0, after_correct=0,
                  lost_correct=0, new_correct=0, before_false_blank_fills=0,
                  after_false_blank_fills=0, changed_wrong=0)
    rows = []
    for target in expected:
        predictions = [index[target['sha256']] for index in indexes]
        parsed = [bind(r['raw'], truncated=r['token_budget_reached']) for r in predictions]
        fields = []
        for key, literal in target['printed_fields'].items():
            truth = iso(literal) if literal and key in DATES else literal or None
            actual = [r['fields'].get(key) if r['document_type'] == target['document_type'] else None for r in parsed]
            correct = [normalized(v) == normalized(truth) if truth is not None and v is not None else v is truth for v in actual]
            if truth is None:
                totals['blank'] += 1
                totals['before_false_blank_fills'] += actual[0] is not None
                totals['after_false_blank_fills'] += actual[1] is not None
            else:
                totals['present'] += 1
                totals['before_correct'] += correct[0]
                totals['after_correct'] += correct[1]
                totals['lost_correct'] += correct[0] and not correct[1]
                totals['new_correct'] += correct[1] and not correct[0]
                totals['changed_wrong'] += not correct[0] and not correct[1] and actual[0] != actual[1]
            fields.append(dict(key=key, printed_literal=literal, expected=truth, before_after=actual, correct=correct))
        rows.append(dict(image=target['image'], sha256=target['sha256'], document_type=target['document_type'],
                         title_matches=[r['document_type'] == target['document_type'] for r in parsed], fields=fields))
    return dict(counts=totals, rows=rows,
                scope='Same-line deterministic binding of native OCR; text only, no graphic/full-app qualification')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve previous evaluation')
    reports = []
    # Read and validate completed inference headers before opening any targets.
    for directory in [args.before, args.after or args.before]:
        one = {}
        for split in ['val', 'test']:
            report = json.loads((directory/f'{split}.json').read_text(encoding='utf-8'))
            if not report.get('complete') or report['precision'] != 'fp32' or report['max_pixels'] != 1003520:
                raise ValueError('Completed matching FP32+1MP inference required')
            if report.get('parameter_dtypes') != ['torch.float32'] or report.get('actual_base_weight_sha256') != '85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db':
                raise ValueError('Actual FP32 foundation identity required')
            if report.get('cuda_matmul_allow_tf32') is not False or report.get('cudnn_allow_tf32') is not False:
                raise ValueError('Both TF32 flags must be explicitly off')
            one[split] = report
        reports.append(one)
    result = dict(mode='paired' if args.after else 'baseline_only', promoted=False,
                  scope='Viewed original synthetic development, shared renderer/fonts; not independent real accuracy', splits={})
    for split in ['val', 'test']:
        expected = [json.loads(line) for line in (args.data/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        if any(sha(args.data/r['image']) != r['sha256'] for r in expected):
            raise ValueError('Dataset image mutated')
        before, after = [r[split] for r in reports]
        # compare enforces exact complete, unique source membership.
        literal = compare(expected, before, after)
        result['splits'][split] = dict(literal=literal, values=values(expected, before, after),
                                      budget_hits=[sum(r['token_budget_reached'] for r in report['rows']) for report in [before, after]],
                                      run_sha256_before_after=[sha(directory/f'{split}.json') for directory in [args.before, args.after or args.before]])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: dict(literal=v['literal']['counts'], values=v['values']['counts'], budget_hits=v['budget_hits']) for k,v in result['splits'].items()}), flush=True)


if __name__ == '__main__':
    main()
