"""Compare stored fields under the existing public date output convention.

Separate from immutable raw-string metrics; never changes observations/truth.
"""
import argparse,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dekanat.extraction import normalize
from dekanat.field_validation import validate_fields,DATE_FIELDS,PERIOD_FIELDS

def public_value(key,value):
    if key not in DATE_FIELDS|PERIOD_FIELDS:return normalize(str(value))
    f={'value':str(value),'status':'found','confidence':1}
    validate_fields({key:f})
    return normalize(f['value'])

def summarize(report):
    summary={'present':0,'correct':0,'correct_found':0,'confident_wrong':0,'raw_format_differences':[]}
    for row in report['rows']:
        for c in row['comparisons']:
            if c['expected'] is None:continue
            expected=c['expected'] if isinstance(c['expected'],list) else [c['expected']]
            f=c['observed'];value=f['value'];summary['present']+=1
            correct=value is not None and public_value(c['field'],value) in {public_value(c['field'],e) for e in expected}
            summary['correct']+=correct;summary['correct_found']+=correct and f['status']=='found';summary['confident_wrong']+=not correct and f['status']=='found'
            if correct and not c.get('correct'):
                summary['raw_format_differences'].append({'id':row['id'],'field':c['field'],'observed':value,'expected':expected,'status':f['status']})
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--before',type=Path,required=True);parser.add_argument('--after',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={'scope':'Stored viewed-development outputs, no new inference or training. Only existing public numeric date/range normalizer applied to reference and observation. Raw truth/output/metrics kept unchanged; statuses/confidence not promoted. This separates punctuation mismatch from wrong digits.',
            'before':summarize(json.loads(args.before.read_text(encoding='utf-8'))),'after':summarize(json.loads(args.after.read_text(encoding='utf-8'))),
            'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [args.before,args.after]}}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
