"""Fresh CPU full-analysis/service gate of isolated prose postprocessing.

Input manifest has only paths/hashes/identifiers; never expected values or answers.
Automatic unsupported types remain unsupported and exercise candidate no-op.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.participantkit.service import prepare_result, load_config
from scripts.participantkit.format_v1 import KINDS, validate, answer
from scripts.experiments.leave_prose_dates import recover


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    records = json.loads(args.inputs.read_text(encoding='utf-8'))['inputs']
    if not records or any(set(r) != {'id', 'input', 'sha256'} for r in records):
        raise ValueError('Only input path/hash/identifier allowed')
    import torch
    torch.set_num_threads(4)
    from dekanat.pipeline import analyze
    types = {v: k for k, v in KINDS.items()}
    config = load_config()
    questions = [{'question_id': 'complete', 'question': 'Содержит ли документ все обязательные сведения?'},
                 {'question_id': 'date', 'question': 'Какова дата заявления?'},
                 {'question_id': 'unknown', 'question': 'Какого цвета глаза студента?'}]
    rows = []
    for spec in records:
        file = Path(spec['input'])
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != spec['sha256']:
            raise ValueError('Input SHA mismatch')
        pages, analysis = analyze(data, file.name, gpu=False)
        snapshot = copy.deepcopy(analysis)
        if analysis['type'] in types:
            kind = types[analysis['type']]
            before, audit = prepare_result(pages, analysis, kind, questions, document_id=spec['id'], gpu=False)
            fields, evidence, changes, rejected = recover(before['fields'], audit['bindings'], analysis)
            after = copy.deepcopy(before)
            after['fields'] = fields
            after['validation'] = validate(fields, kind, config)
            after['answers'] = [{'question_id': q['question_id'], **answer(q['question'], fields, after['validation'], config)}
                                for q in questions]
        else:
            before = after = None
            fields, evidence, changes, rejected = recover({}, {}, analysis)
            if fields or changes:
                raise ValueError('Unsupported type was enriched')
            audit = {'analysis': analysis}
        if analysis != snapshot:
            raise ValueError('Original analysis mutated')
        rows.append({'id': spec['id'], 'input_sha256': spec['sha256'], 'before': before, 'after': after,
                     'audit': audit, 'candidate_bindings': evidence, 'changes': changes, 'rejected': rejected,
                     'seconds': analysis['seconds']})
        args.output.write_text(json.dumps({'scope': 'Fresh CPU full local OCR and automatic type + supported-type '
            'service boundary + isolated candidate. Same inference shared by paired before/after postprocessing. '
            'Viewed external/own development, not independent accuracy or timing benchmark.',
            'planned_count': len(records), 'complete': len(rows) == len(records),
            'inputs_manifest_sha256': hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
            'rows': rows, 'changed': sum(r['before'] != r['after'] for r in rows)},
            ensure_ascii=False, indent=2, default=lambda value: value.tolist()), encoding='utf-8')
        print(spec['id'], analysis['type'], 'changes', len(changes), flush=True)


if __name__ == '__main__':
    main()
