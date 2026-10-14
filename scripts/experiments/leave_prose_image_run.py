"""Full CPU service comparison; never reads control manifests or references."""
import argparse
import copy
import json
from pathlib import Path

from scripts.participantkit.service import analyze_document, load_config
from scripts.participantkit.format_v1 import validate, answer
from scripts.experiments.leave_prose_guarded import recover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    import torch
    torch.set_num_threads(4)
    inputs = sorted(args.inputs.glob('[0-9][0-9]-*.png'))
    if not inputs:
        raise ValueError('No image inputs')
    questions = [{'question_id': 'q1', 'question': 'Какова дата заявления?'},
                 {'question_id': 'q2', 'question': 'Содержит ли документ все обязательные сведения?'}]
    records = []; config = load_config()
    for file in inputs:
        data = analyze_document(file.read_bytes(), file.name, 'academic_leave_application', questions, gpu=False)
        original = copy.deepcopy(data['result'])
        fields, bindings, changes, rejected = recover(original['fields'], data['audit']['bindings'], data['audit']['analysis'])
        candidate = copy.deepcopy(original)
        candidate['fields'] = fields
        candidate['validation'] = validate(fields, candidate['document_type'], config)
        candidate['answers'] = [{'question_id': q['question_id'], **answer(q['question'], fields, candidate['validation'], config)} for q in questions]
        records.append({'image': file.name, 'sha256': data['input_sha256'], 'before': original,
                        'after': candidate, 'changes': changes, 'rejected': rejected,
                        'candidate_bindings': bindings, 'full_service_audit': data['audit'],
                        'seconds': data['seconds']})
        args.output.write_text(json.dumps({'scope': 'Full CPU service + isolated guarded candidate; no deployed change',
            'planned_count': len(inputs), 'complete': len(records) == len(inputs), 'records': records},
            ensure_ascii=False, indent=2, default=lambda value: value.tolist()), encoding='utf-8')
        print(file.name, 'additions', len(changes), 'seconds', round(data['seconds'], 2), flush=True)


if __name__ == '__main__':
    main()
