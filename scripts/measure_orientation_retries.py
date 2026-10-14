"""Warm, paired default-retry diagnostic on 12 known synthetic rotations."""
import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',choices=['before','after'],required=True)
    parser.add_argument('--reference-source',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if args.reference_source:
        sys.path.insert(0,str(args.reference_source))
    import dekanat.schema as schema
    schema.ROOT=root
    from dekanat.pipeline import analyze
    from dekanat.extraction import normalize
    ROOT,SCHEMAS=root,schema.SCHEMAS
    # Load models outside measured cases, using an upright page.
    analyze((ROOT/'data/demo/study.png').read_bytes(),'warm.png',retry=True)
    rows=[]
    for kind in SCHEMAS:
        source=Image.open(ROOT/f'data/demo/{kind}.png').convert('RGB')
        truth=json.loads((ROOT/f'data/demo/{kind}.json').read_text(encoding='utf-8'))['fields']
        for degrees in [0,90,180,270]:
            image=source.rotate(degrees,expand=True)
            buffer=io.BytesIO();image.save(buffer,format='PNG')
            _,result=analyze(buffer.getvalue(),'quarter.png',retry=True)
            fields={key:{k:field[k] for k in ['value','status']} for key,field in result['fields'].items()}
            correct=sum(result['fields'].get(k,{}).get('value') is not None and normalize(str(result['fields'][k]['value']))==normalize(str(v)) for k,v in truth.items() if not isinstance(v,bool))
            wrong=sum(f['status']=='found' and (f['value'] is None or normalize(str(f['value']))!=normalize(str(truth[k]))) for k,f in fields.items() if k in truth and not isinstance(truth[k],bool))
            row={'type':kind,'degrees':degrees,'detected_type':result['type'],'seconds':result['seconds'],
                 'reported_retries':result['ocr']['retries'],'correct':correct,'confident_wrong':wrong,'fields':fields,
                 'orientation':result['orientation']}
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k not in ['fields','orientation']},ensure_ascii=False),flush=True)
    report={'scope':'Single warm pass, 12 known synthetic pages: three types x four orientations. Default retry=True, GPU, entire analyze call including visual marks. Models warmed once, OS/GPU cache not controlled. Not independent real-photo accuracy or a general speed guarantee.',
            'rows':rows,'correct':sum(r['correct'] for r in rows),'total':84,'confident_wrong':sum(r['confident_wrong'] for r in rows),
            'reference_source':str(args.reference_source) if args.reference_source else None,
            'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ((args.reference_source or ROOT)/'dekanat').glob('*.py')}}
    (ROOT/f'artifacts/orientation_retry_{args.name}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
