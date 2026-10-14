"""Stored-output diagnostic, never a fresh model accuracy or training result."""
import argparse
import copy
import json
from pathlib import Path
from scripts.unified.geometry_contract import parse_abstaining
from scripts.unified.compare import grade


def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,nargs='+',required=True)
    p.add_argument('--legacy',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh diagnostic report')
    reports=[];audit=[]
    for file in args.reports:
        report=json.loads(file.read_text(encoding='utf-8'))
        if report.get('complete') is False:raise ValueError('Incomplete output')
        report=copy.deepcopy(report)
        for row in report['records']:
            text=row['raw'].strip();text=text[7:-3].strip() if text.startswith('```json') and text.endswith('```') else text
            try:
                row['prediction'],details=parse_abstaining(text)
                audit.append({'image':row['image'],**details})
            except (TypeError,ValueError) as exc:
                row['prediction']=None;audit.append({'image':row['image'],'rejected':str(exc)})
        reports.append(report)
    result=grade(reports,json.loads(args.legacy.read_text(encoding='utf-8')))
    result['scope']='Stored-output geometry abstention replay; values unchanged; not fresh inference or ML gain'
    result['geometry_audit']=audit
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['counts']))


if __name__=='__main__':main()
