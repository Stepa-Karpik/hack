"""Official contract inference/replay. Never opens reference_results.json.

Use --replay only for diagnostic replay of frozen V21 OCR, not an app benchmark.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from format_v1 import KINDS
from service import prepare_result


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                    default=lambda v: v.tolist()), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=['image','pdf'], required=True)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--crop-recovery', action='store_true', help='Bounded image rereads, never during stored OCR replay')
    parser.add_argument('--text-mark-guard', action='store_true', help='Reject weak signature candidates overlapping printed OCR captions')
    parser.add_argument('--value-quote-recovery', action='store_true', help='Selected quote reader on a bounded value crop')
    args = parser.parse_args()
    if args.replay and (args.crop_recovery or args.value_quote_recovery):
        parser.error('Image recovery requires full inference; replay is diagnostic OCR only')
    if args.output.exists() or args.output.with_suffix('.audit.json').exists():
        raise RuntimeError('Preserve previous results: select a new output path')
    config = json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))
    manifest = json.loads((args.kit/'documents.json').read_text(encoding='utf-8'))
    questions = json.loads((args.kit/'questions.json').read_text(encoding='utf-8'))
    replay = {r['document_id']: r for r in json.loads(args.replay.read_text(encoding='utf-8'))['rows']} if args.replay else None
    if replay is None:
        from dekanat.pipeline import analyze
    results = {'version':'1.0','documents':[]}
    audit = {'mode':'stored_ocr_replay' if replay is not None else 'full_pipeline',
        'scope':'Viewed synthetic development corpus; paired PNG/PDF, not independent accuracy.',
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*Path(__file__).parent.glob('*.py'), ROOT/'configs/participant_v1.json', *(ROOT/'dekanat').glob('*.py')]},
        'rows':[]}
    for record in manifest:
        path = (args.kit/record[args.variant]).resolve()
        if not path.is_relative_to(args.kit.resolve()):
            raise ValueError('Input outside participant kit')
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if replay is not None:
            previous = replay[record['document_id']]
            if digest != previous['input_sha256']:
                raise ValueError('Replay input mismatch')
            analysis = previous['analysis']
        else:
            pages, analysis = analyze(data, path.name, document_type=KINDS[record['document_type']])
        result, details = prepare_result(None if replay is not None else pages, analysis,
            record['document_type'],
            [{'question_id':q['question_id'],'question':q['question']} for q in questions if q['document_id']==record['document_id']],
            config, document_id=record['document_id'], crop_recovery=args.crop_recovery,
            text_mark_guard=args.text_mark_guard, value_quote_recovery=args.value_quote_recovery)
        results['documents'].append(result)
        audit['rows'].append({'document_id':record['document_id'],'input_sha256':digest,**details})
        validation = result['validation']
        print(record['document_id'],len(validation['missing_fields']),'missing',flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write(args.output,results)
    write(args.output.with_suffix('.audit.json'),audit)


if __name__ == '__main__':
    main()
