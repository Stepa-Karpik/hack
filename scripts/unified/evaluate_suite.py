"""Evaluation-only suite. One chosen network reads images without targets."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.unified.model import UnifiedModel
from scripts.unified.run import evaluate


def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True)
    p.add_argument('--adapter',type=Path,required=True);p.add_argument('--data',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=int,default=3)
    p.add_argument('--max-pixels',type=int,default=512*28*28);p.add_argument('--constrained',action='store_true')
    p.add_argument('--geometry-abstention',action='store_true')
    p.add_argument('--precision',choices=['nf4','vision_bf16','bf16'],default='nf4')
    args=p.parse_args()
    if args.limit<0 or args.output.exists():raise ValueError('Fresh output and nonnegative limit required')
    if len({d.name for d in args.data})!=len(args.data):raise ValueError('Dataset names must be unique')
    args.output.mkdir(parents=True)
    (args.output/'suite-config.json').write_text(json.dumps({
        'adapter_sha256':hashlib.sha256((args.adapter/'adapter_model.safetensors').read_bytes()).hexdigest(),
        'max_pixels':args.max_pixels,'limit':args.limit,'constrained':args.constrained,
        'geometry_abstention':args.geometry_abstention,
        'precision_profile':args.precision,
        'dataset_manifests':{d.name:hashlib.sha256((d/'manifest.json').read_bytes()).hexdigest() for d in args.data},
        'scope':'Evaluation only; any viewed validation/test input becomes development'},indent=2),encoding='utf-8')
    net=UnifiedModel(args.base,args.adapter,args.max_pixels,constrained=args.constrained,
                     geometry_abstention=args.geometry_abstention,precision=args.precision)
    for data in args.data:
        for split in ['val','test']:
            evaluate(net,data,split,args.output/f'{data.name}-{split}.json',args.limit)


if __name__=='__main__':main()
