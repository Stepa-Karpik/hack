"""Evaluation-only kit grading; not imported by inference or training."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True)
    p.add_argument('--predictions',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh grading report')
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    predictions=load(args.predictions)
    if not predictions['complete']:raise ValueError('Incomplete inference must not be qualified')
    spec=importlib.util.spec_from_file_location('organizer_grader',args.kit/'evaluate.py')
    evaluator=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluator)
    refs={r['document_id']:r for r in load(args.kit/'reference_results.json')['documents']}
    baseline={r['document_id']:r for r in load(args.baseline)['documents']}
    counts={'documents':len(predictions['rows']),'accepted':0,'fields':0,'correct':0,'legacy_correct':0,
            'lost_legacy_correct':0,'new_correct':0,'filled_absent_text':0,'wrong_nonempty_text':0,
            'raw_literal_correct':0}
    lost=[];errors=[];selected=[];outputs=[]
    for row in predictions['rows']:
        did=row['document_id'];reference=refs[did];result=row['result']
        accepted=result is not None and result['document_type']==reference['document_type']
        raw=None
        try:
            raw=json.loads(row['raw'])
        except (TypeError,ValueError):pass
        counts['accepted']+=bool(accepted);selected.append(reference)
        if accepted:outputs.append(result)
        for key,expected in reference['fields'].items():
            actual=result['fields'][key] if accepted else '__invalid__'
            before=baseline[did]['fields'][key]
            good=evaluator.exact_value(actual,expected);old_good=evaluator.exact_value(before,expected)
            if isinstance(raw,dict) and raw.get('document_type')==reference['document_type'] and isinstance(raw.get('fields'),dict):
                literal=raw['fields'].get(key,'__missing_key__')
                literal='не найдено' if literal is None else literal
                counts['raw_literal_correct']+=evaluator.exact_value(literal,expected)
            counts['fields']+=1;counts['correct']+=good;counts['legacy_correct']+=old_good
            counts['lost_legacy_correct']+=old_good and not good;counts['new_correct']+=good and not old_good
            if accepted and isinstance(actual,str) and actual!='не найдено' and not good:
                counts['wrong_nonempty_text']+=1
                counts['filled_absent_text']+=expected=='не найдено'
            if old_good and not good:lost.append([did,key,before,actual])
            if not good:errors.append([did,key,expected,actual])
    metrics=None
    if len(outputs)==len(selected):
        metrics=evaluator.evaluate({'version':'1.0','documents':selected},{'version':'1.0','documents':outputs})
    report={'scope':'Balanced viewed organizer subset; normalized grading, not independent real accuracy',
            'raw_literal_scope':'Reading diagnostic even if geometry or complete contract fails; never substituted into inference result',
            'counts':counts,'organizer_metrics':metrics,'lost_correct':lost,'errors':errors,
            'promoted':False,'reason':'Subset only; full legacy and deployment gates not completed'}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(counts))


if __name__=='__main__':main()
