"""Guard replay only; no image inference, no production mutation."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.experiments.wrapped_names_guarded import select_rows,accept_proposal


def read(name):return json.loads((ROOT/'artifacts'/name).read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();target=Path(args.output)
    if target.exists():raise FileExistsError(target)
    base=read('wrapped_names_study_v1.json');reread=read('wrapped_names_reread_v1.json');review=read('wrapped_names_adversarial_v2_reviewed.json')
    rows=[]
    for group,items in [('first12',base['rows']),('reviewed16',review['rows'])]:
        for item in items:
            runtime=item['runtime'];before=runtime['result']['fields']['university']
            proposal=item.get('proposal') or next(x['proposal'] for x in reread['rows'] if x['case']==item['case'] and x['font']==item['font'])
            raw=runtime['audit']['analysis']['fields'].get('university',{})
            binding=runtime['audit']['bindings'].get('university',{})
            value,reason=accept_proposal(before,raw,binding,proposal,runtime['ocr']['lines'])
            after=value or before
            rows.append({'group':group,'font':item['font'],'case':item['case'],'expected':item['expected'],'before':before,'after':after,'reason':reason,'changed':after!=before,'before_exact':before==item['expected'],'after_exact':after==item['expected'],'changed_wrong':after!=before and after!=item['expected']})
    eligibility=[]
    for mode in ['image','pdf']:
        audit=read(f'participant_service_v7_{mode}_full.audit.json')
        for item in audit['rows']:
            parts,reason=select_rows(item['analysis'].get('ocr',{}).get('lines',[]))
            raw=item['analysis']['fields'].get('university',{})
            if raw.get('status') in {'found','conflict'}:parts=[];reason='preserve_found_or_conflict'
            eligibility.append({'mode':mode,'document_id':item['document_id'],'eligible':bool(parts),'reason':reason})
    report={'scope':'Stored guard replay on 28 viewed synthetic development inputs. Separate 60-view kit eligibility-only scan: no reread, new predictions or full-app regression claim. Production unchanged.','rows':rows,'groups':{g:{'before_exact':sum(x['before_exact'] for x in rows if x['group']==g),'after_exact':sum(x['after_exact'] for x in rows if x['group']==g),'changed_wrong':sum(x['changed_wrong'] for x in rows if x['group']==g),'changed':sum(x['changed'] for x in rows if x['group']==g)} for g in ['first12','reviewed16']},'kit_eligibility':eligibility,'kit_eligible':sum(x['eligible'] for x in eligibility)}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'groups':report['groups'],'kit_eligible':report['kit_eligible']}))


if __name__=='__main__':main()
