"""Standalone local single-network image analysis, without kit/reference access."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.unified.model import UnifiedModel, read_document
from scripts.unified.contract import official_result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('image',type=Path)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--adapter',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--question',action='append',default=[])
    p.add_argument('--constrained',action='store_true')
    p.add_argument('--max-pixels',type=int,default=512*28*28)
    p.add_argument('--geometry-abstention',action='store_true')
    p.add_argument('--precision',choices=['nf4','vision_bf16','bf16'],default='nf4')
    args=p.parse_args()
    if args.output.exists():
        raise ValueError('Use a fresh output file')
    image=read_document(args.image)
    net=UnifiedModel(args.base,args.adapter,max_pixels=args.max_pixels,constrained=args.constrained,
                     geometry_abstention=args.geometry_abstention,precision=args.precision)
    result=net.predict(image)
    result['input_sha256']=hashlib.sha256(args.image.read_bytes()).hexdigest()
    result['official_result']=official_result(result['prediction'],
        [{'question_id':str(i),'question':text} for i,text in enumerate(args.question)]) if result['prediction'] else None
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Valid structured prediction' if result['prediction'] else 'Rejected model output: '+result['error'])


if __name__=='__main__':main()
