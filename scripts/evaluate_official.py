"""Frozen institutional development/holdout inputs, separate recall and absence."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT,SCHEMAS
from dekanat.pipeline import analyze,ANALYSIS_VERSION
from dekanat.extraction import normalize


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['development','holdout'],default='development')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--truth',type=Path,default=ROOT/'artifacts/official_evaluation_truth.json')
    parser.add_argument('--viewed',action='store_true',help='Explicitly mark reused initial holdout as viewed development')
    args=parser.parse_args()
    truth=json.loads(args.truth.read_text(encoding='utf-8'))
    rows=[]
    counts={'documents':0,'type_correct':0,'present_fields':0,'correct_present':0,'correct_present_found':0,'confident_wrong_present':0,'absent_fields':0,'absent_found':0,'unmarked_inputs':0,'false_confirmed_marks':0}
    for record in truth['records']:
        if record['split']!=args.split:continue
        path=Path(record['input']);data=path.read_bytes()
        assert hashlib.sha256(data).hexdigest()==record['sha256']
        _,result=analyze(data,path.name,retry=True)
        counts['documents']+=1;counts['type_correct']+=result['type']==record['type']
        comparisons=[]
        if record['type'] is not None:
            for key,expected in record['fields'].items():
                f=result['fields'].get(key,{'value':None,'status':'not_found','confidence':0})
                if expected is None:
                    counts['absent_fields']+=1;counts['absent_found']+=f['status']=='found'
                    comparisons.append({'field':key,'expected':None,'observed':f,'false_found':f['status']=='found'})
                else:
                    allowed=expected if isinstance(expected,list) else [expected]
                    correct=f['value'] is not None and normalize(str(f['value'])) in {normalize(v) for v in allowed}
                    counts['present_fields']+=1;counts['correct_present']+=correct
                    counts['correct_present_found']+=correct and f['status']=='found'
                    counts['confident_wrong_present']+=not correct and f['status']=='found'
                    comparisons.append({'field':key,'expected':allowed,'observed':f,'correct':correct})
            if record.get('unmarked'):
                counts['unmarked_inputs']+=1
                counts['false_confirmed_marks']+=sum(result['fields'].get(k,{}).get('status')=='found' and result['fields'].get(k,{}).get('value') is True for k in SCHEMAS[record['type']]['visual'])
        rows.append({'id':record['id'],'source_id':record['source_id'],'institution':record['institution'],'input_sha256':record['sha256'],'expected_type':record['type'],'analysis':result,'comparisons':comparisons})
        print(record['id'],result['type'],'expected',record['type'],flush=True)
    report={'scope':truth['scope'],'split':args.split,'evaluation_role':'Viewed development re-evaluation, not independent holdout' if args.viewed else 'Initial frozen cohort evaluation; becomes viewed once results inspected','version':ANALYSIS_VERSION,'summary':counts,'rows':rows,
            'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')}}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:x.tolist()),encoding='utf-8')
    print(json.dumps(counts,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
