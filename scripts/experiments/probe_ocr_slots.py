"""Re-score stored OCR output with isolated missing-slot proposals, no inference."""
from pathlib import Path
import sys,json,copy,hashlib
from collections import defaultdict
from field_slots_offline import propose
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.extraction import merge_rows,normalize
from dekanat.field_validation import validate_fields

def evaluate(rows):
    output=[];summary={'present':0,'before_correct':0,'after_correct':0,'new_wrong_found':[],'correct_found_lost':[]}
    for row in rows:
        after=copy.deepcopy(row['analysis']);groups=defaultdict(list)
        for c in propose(merge_rows(after['ocr']['lines']),after['type']):groups[c['key']].append(c)
        for key,options in groups.items():
            field=after['fields'].get(key)
            if field is None or field['value'] is not None or len({c['value'] for c in options})!=1:continue
            c=options[0];score=c['evidence']['confidence']
            after['fields'][key]={'value':c['value'],'confidence':score,'status':'found' if score>=.55 else 'uncertain','evidence':c['evidence']}
        validate_fields(after['fields']);changes=[]
        for previous in row['comparisons']:
            key=previous['field'];expected=previous['expected'];old=previous['observed'];new=after['fields'].get(key,{'value':None,'status':'not_found'})
            if expected is None:
                if new['status']=='found' and old['status']!='found':summary['new_wrong_found'].append(row['id']+'/'+key)
                continue
            allowed=expected if isinstance(expected,list) else [expected]
            if key=='practice_period':allowed=[v.replace(' — ',' - ') for v in allowed]
            correct=new['value'] is not None and normalize(str(new['value'])) in {normalize(v) for v in allowed}
            summary['present']+=1;summary['before_correct']+=bool(previous.get('correct'));summary['after_correct']+=correct
            if old['status']=='found' and previous.get('correct') and not(correct and new['status']=='found'):summary['correct_found_lost'].append(row['id']+'/'+key)
            if not correct and new['status']=='found' and not(old['status']=='found' and not previous.get('correct')):summary['new_wrong_found'].append(row['id']+'/'+key)
            if old['value']!=new['value'] or old['status']!=new['status']:changes.append({'field':key,'before':old,'after':new,'correct':correct})
        output.append({'id':row['id'],'changes':changes})
    return {'summary':summary,'rows':output}

results={}
for name in ['official_development_v17.json','official_viewed_sources_v17.json','official_tsu_v17_viewed.json','official_round3_v17_initial_adjudicated.json','official_camera_v17.json']:
    source=ROOT/'artifacts'/name;report=json.loads(source.read_text(encoding='utf-8'))
    result=evaluate(report['rows']);result['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest();results[name]=result
    print(name,result['summary'])
report={'scope':'Offline replay of stored viewed OCR outputs. No new OCR inference or model training; slot proposals are not deployed. Existing nonempty/conflict values preserved; source-confidence capped. This is not independent source or real-phone accuracy. Numeric date range separators follow public normalization convention.','results':results,
        'experiment_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}}
(ROOT/'artifacts/ocr_slots_shadow_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
