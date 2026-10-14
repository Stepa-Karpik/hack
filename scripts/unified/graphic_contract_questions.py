"""Add requested questions to completed one-backbone results, no reference file.

Document identities only bind question requests to cached predictions. They
never determine fields, type, mark predictions or replacement literal values.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.participantkit.format_v1 import answer
from scripts.participantkit.service import load_config


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh contract output required')
    data = json.loads(args.predictions.read_text(encoding='utf-8'))
    if not data['complete']:
        raise ValueError('Complete inference required')
    documents = json.loads((args.kit/'documents.json').read_text(encoding='utf-8'))
    questions = json.loads((args.kit/'questions.json').read_text(encoding='utf-8'))
    identities = {}
    for record in documents:
        for variant in ('image', 'pdf'):
            path = (args.kit/record[variant]).resolve()
            if not path.is_relative_to(args.kit.resolve()):
                raise ValueError('Input outside manifest root')
            identities[hashlib.sha256(path.read_bytes()).hexdigest()] = (record['document_id'], variant)
    config = load_config()
    rows = []
    for original in data['rows']:
        row = copy.deepcopy(original)
        did, variant = identities[row['input_sha256']]
        row['document_id'], row['variant'] = did, variant
        if row['result'] is not None:
            result = row['result']
            result['document_id'] = did
            result['answers'] = [{'question_id': q['question_id'],
                **answer(q['question'], result['fields'], result['validation'], config)}
                for q in questions if q['document_id'] == did]
        rows.append(row)
    args.output.write_text(json.dumps({**data, 'rows': rows, 'question_request_sha256':
        hashlib.sha256((args.kit/'questions.json').read_bytes()).hexdigest(),
        'reference_read': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Added question requests to', len(rows), 'cached predictions without rerunning OCR')


if __name__ == '__main__':
    main()
