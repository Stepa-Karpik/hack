"""Full paired CPU kit run. Reads manifest/questions, never reference answers."""
import argparse
import copy
import json
from pathlib import Path

from scripts.participantkit.service import analyze_document, load_config
from scripts.participantkit.format_v1 import validate, answer
from scripts.experiments.leave_prose_dates import recover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    import torch
    torch.set_num_threads(4)
    config = load_config()
    documents = json.loads((args.kit/'documents.json').read_text(encoding='utf-8'))
    questions = json.loads((args.kit/'questions.json').read_text(encoding='utf-8'))
    rows = []; changed = []
    for variant in ['image', 'pdf']:
        for spec in documents:
            path = (args.kit/spec[variant]).resolve()
            if not path.is_relative_to(args.kit.resolve()):
                raise ValueError('Input outside kit')
            qs = [{'question_id': q['question_id'], 'question': q['question']}
                  for q in questions if q['document_id'] == spec['document_id']]
            data = analyze_document(path.read_bytes(), path.name, spec['document_type'], qs,
                                    gpu=False, document_id=spec['document_id'])
            before = copy.deepcopy(data['result'])
            fields, bindings, changes, rejected = recover(before['fields'], data['audit']['bindings'], data['audit']['analysis'])
            after = copy.deepcopy(before); after['fields'] = fields
            after['validation'] = validate(fields, spec['document_type'], config)
            after['answers'] = [{'question_id': q['question_id'], **answer(q['question'], fields, after['validation'], config)} for q in qs]
            if after != before:
                changed.append({'variant': variant, 'document_id': spec['document_id']})
            rows.append({'variant': variant, 'input_sha256': data['input_sha256'], 'before': before, 'after': after,
                         'audit': data['audit'], 'candidate_bindings': bindings, 'changes': changes,
                         'rejected': rejected, 'seconds': data['seconds']})
            args.output.write_text(json.dumps({'scope': 'Full CPU paired kit service + isolated pure candidate; viewed synthetic development, not independent accuracy',
                'planned_count': len(documents)*2, 'complete': len(rows) == len(documents)*2,
                'changed_outputs': changed, 'rows': rows}, ensure_ascii=False, indent=2,
                default=lambda value: value.tolist()), encoding='utf-8')
            print(variant, spec['document_id'], 'changes', len(changes), 'seconds', round(data['seconds'], 2), flush=True)


if __name__ == '__main__':
    main()
