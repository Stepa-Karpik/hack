"""Literal and geometry grading only; no grading inputs can reach inference."""
import argparse
import json
from pathlib import Path
from scripts.unified.contract import MARKS


def iou(a,b):
    if a is None or b is None:return 0.
    x=max(0,min(a[2],b[2])-max(a[0],b[0]))
    y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=x*y
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0.


def grade(reports,legacy):
    previous={r['sha256']:r for r in legacy['records']}
    counts={k:0 for k in ['documents','valid_json','fields','correct','text_fields','correct_text',
                          'mark_fields','correct_marks','wrong_nonempty_text','filled_absent_text',
                          'lost_legacy_correct','new_correct','geometry_expected','correct_value_iou50',
                          'raw_literal_correct']}
    details=[]
    for report in reports:
        if report.get('complete') is False:
            raise ValueError('Partial prediction report is diagnostic only; wait for evaluation completion')
        for row in report['records']:
            counts['documents']+=1
            target=row['expected'];prediction=row['prediction']
            raw=None
            try:
                text=row['raw'].strip()
                text=text[7:-3].strip() if text.startswith('```json') and text.endswith('```') else text
                raw=json.loads(text)
            except (ValueError,TypeError):pass
            good_type=prediction and prediction['document_type']==target['document_type']
            counts['valid_json']+=prediction is not None
            prior=previous[row['sha256']]
            changes=[]
            for key,expected in target['fields'].items():
                actual=prediction['fields'][key] if good_type else '__invalid__'
                correct=actual==expected
                # Separate reading diagnostics from the strict, integration-ready contract.
                if isinstance(raw,dict) and raw.get('document_type')==target['document_type'] and isinstance(raw.get('fields'),dict):
                    literal=raw['fields'].get(key,'__absent_key__')
                    counts['raw_literal_correct']+=type(literal) is type(expected) and literal==expected
                baseline=prior['result']['fields'][key]
                baseline_correct=baseline==('не найдено' if expected is None else expected)
                counts['fields']+=1;counts['correct']+=correct
                if key in MARKS:
                    counts['mark_fields']+=1;counts['correct_marks']+=correct
                else:
                    counts['text_fields']+=1;counts['correct_text']+=correct
                    if good_type and actual is not None and not correct:
                        counts['wrong_nonempty_text']+=1
                        counts['filled_absent_text']+=expected is None
                counts['lost_legacy_correct']+=baseline_correct and not correct
                counts['new_correct']+=correct and not baseline_correct
                bbox=target['boxes'][key]
                if bbox is not None:
                    counts['geometry_expected']+=1
                    counts['correct_value_iou50']+=bool(correct and good_type and iou(prediction['boxes'][key],bbox)>=.5)
                if not correct:changes.append({'field':key,'expected':expected,'predicted':actual,'legacy':baseline})
            details.append({'image':row['image'],'sha256':row['sha256'],'errors':changes,'seconds':row['seconds']})
    return {'scope':'paired viewed synthetic renderer inputs; not real-world accuracy or speed benchmark',
            'metric_definitions':{'correct':'Exact literal from a fully accepted strict prediction',
                'raw_literal_correct':'Exact typed scalar in raw JSON, even if other fields or geometry fail. Diagnostic only.',
                'valid_json':'Historical name: full strict contract accepted, not merely JSON syntax'},
            'legacy_hardware':'CPU','unified_hardware':'GPU','counts':counts,'details':details,
            'promoted':False,'reason':'Full production regression gates and independent real validation not executed'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,nargs='+',required=True)
    p.add_argument('--legacy',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh report path')
    result=grade([json.loads(f.read_text(encoding='utf-8')) for f in args.reports],
                 json.loads(args.legacy.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['counts']))


if __name__=='__main__':main()
