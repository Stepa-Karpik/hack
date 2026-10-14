"""Organizer grading after complete paired inference; no generation access."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh grading output required')
    report = json.loads(args.predictions.read_text(encoding='utf-8'))
    if not report['complete'] or len(report['rows']) != report['planned_count']:
        raise ValueError('Full inference required before grading')
    spec = importlib.util.spec_from_file_location('organizer_grader', args.kit/'evaluate.py')
    evaluator = importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluator)
    reference = json.loads((args.kit/'reference_results.json').read_text(encoding='utf-8'))
    outputs = {}; changed = []
    for variant in ['image', 'pdf']:
        records = [r for r in report['rows'] if r['variant'] == variant]
        ids = [r['before']['document_id'] for r in records]
        if len(set(ids)) != len(ids) or set(ids) != {r['document_id'] for r in reference['documents']}:
            raise ValueError('Missing or duplicate representation records')
        outputs[variant] = {phase: evaluator.evaluate(reference, {'version': '1.0',
            'documents': [r[phase] for r in records]}) for phase in ['before', 'after']}
        changed.extend({'variant': variant, 'document_id': r['before']['document_id']}
                       for r in records if r['before'] != r['after'])
    args.output.write_text(json.dumps({'scope': 'Full paired CPU organizer development; not independent real accuracy',
        'metrics': outputs, 'changed_outputs': changed, 'deployed': False,
        'all_legacy_gates_passed': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(outputs))


if __name__ == '__main__':
    main()
