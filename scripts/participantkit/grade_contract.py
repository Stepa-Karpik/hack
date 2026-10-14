"""Evaluation only: inspect official predictions, keeping references out of inference."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kit',type=Path,required=True)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():
        raise RuntimeError('Preserve previous metrics; choose a new report path')
    # Supplied evaluate.py was inspected before use; audit SHA in kit intake.
    spec=importlib.util.spec_from_file_location('organizer_evaluator',args.kit/'evaluate.py')
    evaluator=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluator)
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    reference=load(args.kit/'reference_results.json')
    predicted=load(args.predictions)
    baseline=load(args.baseline)
    metrics=evaluator.evaluate(reference,predicted)
    old={r['document_id']:r for r in baseline['documents']}
    new={r['document_id']:r for r in predicted['documents']}
    lost=[];gained=[];wrong=[]
    for ref in reference['documents']:
        did=ref['document_id']
        for key,value in ref['fields'].items():
            before=old[did]['fields'][key];after=new[did]['fields'][key]
            a=evaluator.exact_value(before,value);b=evaluator.exact_value(after,value)
            if a and not b:lost.append([did,key,before,after])
            if b and not a:gained.append([did,key])
            if not b and before!=after:wrong.append([did,key,before,after])
    metrics['paired_changes']={'lost_correct':lost,'gained_correct':gained,'changed_to_wrong':wrong}
    metrics['scope']='Viewed synthetic development set; changed wrong literals are not necessarily confident. Inspect binding audit statuses separately.'
    args.report.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:metrics[k] for k in ['field_accuracy_macro','validation_exact_match','question_exact_match']},
        'lost',len(lost),'gained',len(gained),'changed_wrong',len(wrong))


if __name__=='__main__':main()
