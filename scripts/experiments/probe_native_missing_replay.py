"""Stored-output replay, no app route/inference; keep all nonempty/conflicts."""
from pathlib import Path
import json,copy,hashlib,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.extraction import normalize
from dekanat.field_validation import validate_fields

def enrich(old, native):
    fields=copy.deepcopy(old);changes=[]
    for key,candidate in native.items():
        previous=fields.get(key)
        if (not previous or previous.get('value') is not None or previous.get('status')!='not_found'
            or candidate.get('value') is None or candidate.get('status')!='found'):
            continue
        fields[key]=copy.deepcopy(candidate)
        fields[key]['diagnostic_source']='native_pdf_missing_replay_not_deployed'
        changes.append(key)
    validate_fields(fields)
    return fields,changes

def run():
    native=json.loads((ROOT/'artifacts/native_pdf_fields_candidate_v20.json').read_text(encoding='utf-8'))
    eligibility={r['id']:r for r in json.loads((ROOT/'artifacts/native_pdf_eligibility_probe.json').read_text(encoding='utf-8'))['institutional']}
    previous={r['id']:r for n in ['official_development_v20.json','official_viewed_sources_v20.json','official_tsu_v20_viewed.json','official_round3_v20_viewed.json']
              for r in json.loads((ROOT/'artifacts'/n).read_text(encoding='utf-8'))['rows']}
    truth={r['id']:r for n in ['official_evaluation_truth.json','official_extra_evaluation_truth.json','official_round3_evaluation_truth_v2.json']
           for r in json.loads((ROOT/'artifacts'/n).read_text(encoding='utf-8'))['records']}
    rows=[];summary={'present':0,'before_correct':0,'after_correct':0,'after_correct_found':0,'lost_correct_found':0,'new_wrong_found':0,'absent_found':0}
    for row in native['rows']:
        before=previous[row['id']]['analysis']['fields']
        assert previous[row['id']]['input_sha256']==row['input_sha256']==eligibility[row['id']]['sha256']
        fields,changes=enrich(before,row['fields']) if eligibility[row['id']]['inspection']['eligible'] else (copy.deepcopy(before),[])
        comparisons=[]
        for key,expected in truth[row['id']]['fields'].items():
            old=before.get(key,{'value':None,'status':'not_found'});after=fields.get(key,{'value':None,'status':'not_found'})
            if expected is None:
                summary['absent_found']+=after['status']=='found'
                continue
            allowed=expected if isinstance(expected,list) else [expected]
            if key=='practice_period':allowed=[v.replace(' — ',' - ') for v in allowed]
            def correct(field):return field['value'] is not None and normalize(str(field['value'])) in {normalize(v) for v in allowed}
            bc,ac=correct(old),correct(after)
            lost=bc and old['status']=='found' and not(ac and after['status']=='found')
            wrong=not ac and after['status']=='found' and not(not bc and old['status']=='found')
            summary['present']+=1;summary['before_correct']+=bc;summary['after_correct']+=ac
            summary['after_correct_found']+=ac and after['status']=='found';summary['lost_correct_found']+=lost;summary['new_wrong_found']+=wrong
            comparisons.append({'field':key,'before':old,'after':after,'correct_before':bc,'correct_after':ac})
        rows.append({'id':row['id'],'changes':changes,'comparisons':comparisons})
    own_native=json.loads((ROOT/'artifacts/native_pdf_own_candidate_v20.json').read_text(encoding='utf-8'))
    own_old={r['file']:r for r in json.loads((ROOT/'artifacts/realistic_documents_after_v20.json').read_text(encoding='utf-8'))['rows']}
    own=[];own_lost=[];own_wrong=[]
    for row in own_native['rows']:
        before=own_old[row['file']]['analysis']['fields'];assert own_old[row['file']]['sha256']==row['sha256']
        fields,changes=enrich(before,row['fields']) if row['eligibility']['eligible'] else (copy.deepcopy(before),[])
        for c in row['comparisons']:
            old=before.get(c['field'],{'value':None,'status':'not_found'});after=fields.get(c['field'],{'value':None,'status':'not_found'})
            def correct(f):return f['value'] is not None and normalize(str(f['value']))==normalize(str(c['expected']))
            if correct(old) and old['status']=='found' and not(correct(after) and after['status']=='found'):own_lost.append([row['file'],c['field']])
            if not correct(after) and after['status']=='found' and not(not correct(old) and old['status']=='found'):own_wrong.append([row['file'],c['field']])
        own.append({'file':row['file'],'changes':changes,'fields':fields})
    report={'scope':'Stored-output offline missing-only replay on 23 viewed institutional and six own PDFs. Public period format comparison. No app integration, training, full visual/fallback benchmark or speed claim. Source1 not calibrated semantic confidence. Preserve nonempty/conflict; eligibility allows enrichment only.',
        'summary':summary,'own_lost_correct_found':own_lost,'own_new_wrong_found':own_wrong,'rows':rows,'own':own,
        'paired_passed':not summary['lost_correct_found'] and not summary['new_wrong_found'] and not summary['absent_found'] and not own_lost and not own_wrong,
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (ROOT/'artifacts/native_pdf_missing_replay_v20.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','own'}},ensure_ascii=False))

if __name__=='__main__':run()
