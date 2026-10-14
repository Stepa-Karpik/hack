"""Compare default retry=True on 57 controlled camera-like cases.

Optional reference-source points to a locally saved immutable dekanat package;
only its schema ROOT is redirected to the same deployed assets/data.
"""
import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',choices=['before','after'],required=True)
    parser.add_argument('--reference-source',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(args.reference_source or root))
    import dekanat.schema as schema
    schema.ROOT=root
    from dekanat.pipeline import analyze
    from dekanat.photo_augment import conditions
    from dekanat.extraction import normalize
    rows=[]
    analyze((root/'data/demo/study.png').read_bytes(),'warm.png',retry=True)
    for kind in schema.SCHEMAS:
        truth=json.loads((root/f'data/demo/{kind}.json').read_text(encoding='utf-8'))['fields']
        source=Image.open(root/f'data/demo/{kind}.png').convert('RGB')
        for name,transform in conditions().items():
            image=transform(source);buffer=io.BytesIO();image.save(buffer,format='PNG')
            _,result=analyze(buffer.getvalue(),'camera.png',kind,retry=True)
            fields={key:{k:field[k] for k in ['value','status']} for key,field in result['fields'].items() if key in truth and not isinstance(truth[key],bool)}
            equal=lambda key:fields[key]['value'] is not None and normalize(str(fields[key]['value']))==normalize(str(truth[key]))
            row={'type':kind,'condition':name,'fields':fields,'correct':sum(equal(k) for k in fields),
                 'confident_wrong':sum(f['status']=='found' and not equal(k) for k,f in fields.items()),
                 'seconds':result['seconds'],'orientation':result['orientation']}
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k not in ['fields','orientation']}),flush=True)
    source_root=args.reference_source or root
    report={'scope':'57 known synthetic camera-like cases, three document types, retry=True, manual type; text fields only. Development regression, not real-photo accuracy.',
            'reference_source':str(args.reference_source) if args.reference_source else None,
            'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source_root/'dekanat').glob('*.py')},
            'correct':sum(r['correct'] for r in rows),'total':399,'confident_wrong':sum(r['confident_wrong'] for r in rows),'rows':rows}
    target=args.report or root/f'artifacts/default_retry_{args.name}.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
