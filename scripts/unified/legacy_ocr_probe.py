"""Existing OCR-stage comparator only, not whole-app predictions."""
import argparse,hashlib,json,time
from pathlib import Path
from scripts.unified.model import read_document
from dekanat.ocr import recognize

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--gpu',action='store_true');args=p.parse_args()
    if args.output.exists():raise ValueError('Fresh output required')
    rows=[]
    for file in args.inputs:
        start=time.perf_counter();result=recognize([read_document(file)],gpu=args.gpu)
        # Preserve the OCR engine's reading order; sorting by y alone reverses
        # fragments of a shared row when their glyph ascenders differ.
        raw='\n'.join(line['text'] for line in result['lines'])
        rows.append({'file':file.name,'input_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                     'raw':raw,'ocr':result,'seconds':time.perf_counter()-start})
        args.output.write_text(json.dumps({'scope':'Existing OCR-stage diagnostic only; not full app accuracy',
            'device':'cuda' if args.gpu else 'cpu','complete':len(rows)==len(args.inputs),'rows':rows},
            ensure_ascii=False,indent=2),encoding='utf-8')
        print(file.name,'lines',len(result['lines']),flush=True)

if __name__=='__main__':main()
