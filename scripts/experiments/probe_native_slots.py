from pathlib import Path
import sys,json,copy
from collections import defaultdict
from field_slots_offline import propose
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.extraction import merge_rows,normalize
from dekanat.field_validation import validate_fields
original=json.loads((ROOT/'artifacts/native_pdf_all_probe_v18.json').read_text(encoding='utf-8'))
report=copy.deepcopy(original)
truth={r['id']:r for filename in ['official_evaluation_truth.json','official_extra_evaluation_truth.json','official_round3_evaluation_truth_v2.json'] for r in json.loads((ROOT/'artifacts'/filename).read_text(encoding='utf-8'))['records']}
summaries={}
for row in report['rows']:
    candidates=propose(merge_rows(row['lines'] or []),row['type']);groups=defaultdict(list)
    for c in candidates:groups[c['key']].append(c)
    row['proposals']=candidates
    for key,options in groups.items():
        field=row['fields'].get(key)
        if field is None or field['value'] is not None or len({c['value'] for c in options})!=1:continue
        c=options[0];row['fields'][key]={'value':c['value'],'confidence':c['evidence']['confidence'],'status':'found','evidence':c['evidence']}
    validate_fields(row['fields'])
    s=summaries.setdefault(row['cohort'],{'present':0,'correct':0,'correct_found':0,'confident_wrong':0,'absent':0,'absent_found':0})
    row['comparisons']=[]
    for key,expected in truth[row['id']]['fields'].items():
        f=row['fields'].get(key,{'value':None,'status':'not_found','confidence':0})
        if expected is None:s['absent']+=1;s['absent_found']+=f['status']=='found';continue
        allowed=expected if isinstance(expected,list) else [expected]
        # Numeric date separators are equivalent under the existing public normalizer.
        if key=='practice_period':allowed=[v.replace(' — ',' - ') for v in allowed]
        correct=f['value'] is not None and normalize(str(f['value'])) in {normalize(v) for v in allowed}
        s['present']+=1;s['correct']+=correct;s['correct_found']+=correct and f['status']=='found';s['confident_wrong']+=not correct and f['status']=='found'
        row['comparisons'].append({'field':key,'expected':allowed,'observed':f,'correct':correct})
report['scope']+=' Additional offline missing-slot proposals on viewed development. Date range separators normalized using existing public date convention; no known field/conflict replaced. This remains unqualified: placeholder supervisor false positive in base native extraction, uncalibrated source-confidence and no visible-layer check.'
report['summary']=summaries
(ROOT/'artifacts/native_pdf_slots_probe_v18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summaries,ensure_ascii=False))
