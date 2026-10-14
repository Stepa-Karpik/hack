"""Institutional layout development under deterministic camera simulations."""
import argparse,hashlib,io,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);parser.add_argument('--runtime-source',type=Path)
    args=parser.parse_args();sys.path.insert(0,str(args.runtime_source or ROOT))
    from dekanat import schema
    schema.ROOT=ROOT
    from dekanat.pipeline import analyze
    from dekanat.io import read_pages
    from dekanat.photo_augment import conditions
    from dekanat.extraction import normalize
    import dekanat
    truth=json.loads((ROOT/'artifacts/official_evaluation_truth.json').read_text(encoding='utf-8'))
    inputs=[r for r in truth['records'] if r['id'].startswith(('hse_family_filled','rudn_character_filled'))]
    rows=[]
    for record in inputs:
        path=Path(record['input']);data=path.read_bytes();assert hashlib.sha256(data).hexdigest()==record['sha256']
        pages=read_pages(data,path.name);assert len(pages)==1
        for condition,transform in conditions().items():
            buffer=io.BytesIO();transform(pages[0]).save(buffer,format='PNG');pixels=buffer.getvalue()
            _,result=analyze(pixels,'official-camera.png',retry=True)
            comparisons=[]
            for key,expected in record['fields'].items():
                field=result['fields'].get(key,{'value':None,'status':'not_found','confidence':0})
                allowed=expected if isinstance(expected,list) else [expected]
                correct=expected is not None and field['value'] is not None and normalize(str(field['value'])) in {normalize(v) for v in allowed}
                comparisons.append({'field':key,'expected':expected,'observed':field,'correct':correct,
                                    'false_found':expected is None and field['status']=='found'})
            rows.append({'id':record['id']+'/'+condition,'source_id':record['source_id'],'condition':condition,
                         'input_sha256':hashlib.sha256(pixels).hexdigest(),'original_pdf_sha256':record['sha256'],
                         'expected_type':record['type'],'analysis':result,'comparisons':comparisons})
            print(record['id'],condition,flush=True)
    fields=[f for r in rows for f in r['comparisons']]
    report={'scope':'Four viewed fictional filled institutional development templates, 19 deterministic camera simulations each. Not independent source holdout, not actual phone photos or real student documents; no weight training. Full output includes absence and unsupported-type errors. Timing is not a benchmark if other GPU jobs run.',
            'summary':{'documents':len(rows),'type_correct':sum(r['analysis']['type']==r['expected_type'] for r in rows),
                       'present_fields':sum(f['expected'] is not None for f in fields),'correct_present':sum(f['correct'] for f in fields),
                       'correct_present_found':sum(f['correct'] and f['observed']['status']=='found' for f in fields),
                       'confident_wrong_present':sum(f['expected'] is not None and not f['correct'] and f['observed']['status']=='found' for f in fields),
                       'absent_fields':sum(f['expected'] is None for f in fields),'absent_found':sum(f['false_found'] for f in fields),
                       'false_confirmed_marks':sum(f.get('status')=='found' and f.get('value') is True for r in rows for k,f in r['analysis']['fields'].items() if k in {'signature','stamp'})},
            'rows':rows,'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(dekanat.__file__).parent.glob('*.py')}}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:x.tolist()),encoding='utf-8')
    print(json.dumps(report['summary']),flush=True)


if __name__=='__main__':main()
