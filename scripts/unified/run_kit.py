"""Organizer-image inference diagnostic. Never opens reference_results.json."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.unified.model import UnifiedModel, read_document
from scripts.unified.contract import official_result


def main():
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--variant',choices=['image','pdf'],default='image')
    p.add_argument('--limit-per-type',type=int,default=2);p.add_argument('--constrained',action='store_true')
    p.add_argument('--max-pixels',type=int,default=512*28*28)
    p.add_argument('--geometry-abstention',action='store_true')
    p.add_argument('--precision',choices=['nf4','vision_bf16','bf16'],default='nf4')
    p.add_argument('--family',choices=['qwen','paddle'],default='qwen')
    args=p.parse_args()
    if args.output.exists() or args.limit_per_type<0:raise ValueError('Fresh output and nonnegative budget required')
    documents=json.loads((args.kit/'documents.json').read_text(encoding='utf-8'))
    questions=json.loads((args.kit/'questions.json').read_text(encoding='utf-8'))
    selected=[];counts={}
    for record in documents:
        kind=record['document_type'];counts.setdefault(kind,0)
        if args.limit_per_type and counts[kind]>=args.limit_per_type:continue
        selected.append(record);counts[kind]+=1
    args.output.parent.mkdir(parents=True,exist_ok=True)
    model_class=UnifiedModel
    if args.family=='paddle':
        from scripts.unified.paddle_model import PaddleDocumentModel
        model_class=PaddleDocumentModel
    net=model_class(args.base,args.adapter,args.max_pixels,constrained=args.constrained,
                     geometry_abstention=args.geometry_abstention,precision=args.precision)
    rows=[]
    for record in selected:
        file=(args.kit/record[args.variant]).resolve()
        if not file.is_relative_to(args.kit.resolve()):raise ValueError('Manifest input outside kit')
        image=read_document(file)
        # Only the pixels reach the network. IDs and schema metadata select evaluation rows.
        prediction=net.predict(image)
        qs=[{'question_id':q['question_id'],'question':q['question']} for q in questions
            if q['document_id']==record['document_id']]
        result=official_result(prediction['prediction'],qs) if prediction['prediction'] is not None else None
        audit=result.pop('audit') if result is not None else None
        if result is not None:result['document_id']=record['document_id']
        rows.append({'document_id':record['document_id'],'input_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                     **prediction,'result':result,'field_audit':audit})
        args.output.write_text(json.dumps({'scope':'Viewed organizer synthetic development; evaluation only, no training',
            'variant':args.variant,'planned_count':len(selected),'complete':len(rows)==len(selected),
            'max_pixels':args.max_pixels,'geometry_abstention':args.geometry_abstention,
            'precision_profile':args.precision,
            'model_family':args.family,
            'adapter_sha256':hashlib.sha256((args.adapter/'adapter_model.safetensors').read_bytes()).hexdigest(),
            'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        print(record['document_id'],'accepted',prediction['prediction'] is not None,flush=True)


if __name__=='__main__':main()
