"""Grade completed source-bound OCR outputs; targets never enter inference."""
import argparse
import json
from pathlib import Path
from scripts.unified.prepare_literal_training import sha
from scripts.unified.grade_literal_fullpage import compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve prior grading')
    reports = {s: json.loads((args.run / f'baseline-{s}.json').read_text(encoding='utf-8')) for s in ['val', 'test']}
    if not all(r.get('complete') and r['precision'] == 'fp32' and r['max_pixels'] == 1003520
               and r['cuda_matmul_allow_tf32'] is False and r['cudnn_allow_tf32'] is False
               for r in reports.values()):
        raise ValueError('Both completed strict FP32 1MP baselines required')
    result = {'scope': 'First baseline on new fictional diversity, shared renderer/text pools; not independent real/app accuracy',
              'training_done': False, 'promoted': False, 'splits': {}}
    for split, report in reports.items():
        targets = [json.loads(line) for line in (args.data / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        for row in targets:
            if sha(args.data / row['image']) != row['sha256']:
                raise ValueError('Dataset pixels changed')
        target_shas = {t['sha256'] for t in targets}
        extra = [r for r in report['rows'] if r['input_sha256'] not in target_shas]
        # The initial shell glob also submitted the visual-QA sheet. Preserve it,
        # explicitly exclude its unrelated OCR, and reject any other extra input.
        if extra and not (split == 'val' and len(extra) == 1 and extra[0]['file'] == 'val-contact-sheet.png'
                          and extra[0]['input_sha256'] == sha(args.data / 'val-contact-sheet.png')):
            raise ValueError('Unexpected extra inference input')
        report = dict(report, rows=[r for r in report['rows'] if r['input_sha256'] in target_shas])
        # Self comparison provides baseline literal/CER/blank counts without fabricating gains.
        metrics = compare(targets, report, report)
        metrics['budget_hits'] = sum(r['token_budget_reached'] for r in report['rows'])
        metrics['excluded_extra_diagnostic_rows'] = extra
        metrics['by_layout'] = {str(k): compare([r for r in targets if r['layout'] == k],
            dict(report, rows=[r for r in report['rows'] if r['input_sha256'] in {t['sha256'] for t in targets if t['layout'] == k}]),
            dict(report, rows=[r for r in report['rows'] if r['input_sha256'] in {t['sha256'] for t in targets if t['layout'] == k}]))['counts'] for k in range(4)}
        result['splits'][split] = metrics
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({s: r['counts'] for s, r in result['splits'].items()}), flush=True)


if __name__ == '__main__':
    main()
