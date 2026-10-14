"""Evaluation-only paired CPU baseline. Never imported by VLM inference.

Legacy inference receives its required manually selected type; no field targets.
The unified model infers type itself. Hardware timings are not comparable.
"""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.participantkit.service import analyze_document


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=int,default=0)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh immutable report')
    if args.limit<0:raise ValueError('Invalid limit')
    records=[];correct=total=0
    for split in ['val','test']:
        rows=[json.loads(line) for line in (args.data/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        for row in (rows[:args.limit] if args.limit else rows):
            file=args.data/row['image'];data=file.read_bytes()
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Input SHA mismatch')
            response=analyze_document(data,file.name,row['target']['document_type'],[],gpu=False)
            expected={k:('не найдено' if v is None else v) for k,v in row['target']['fields'].items()}
            fields_correct=sum(type(response['result']['fields'][k]) is type(v) and response['result']['fields'][k]==v
                               for k,v in expected.items())
            total+=len(expected);correct+=fields_correct
            records.append({'image':row['image'],'sha256':row['sha256'],'expected':expected,
                            **response,'fields_correct':fields_correct})
            args.output.write_text(json.dumps({'scope':'paired synthetic renderer development; CPU baseline with manually selected type; not comparable speed',
                'fields_correct':correct,'fields_total':total,'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
            print(f'{row["image"]}: {fields_correct}/{len(expected)}',flush=True)


if __name__=='__main__':main()
