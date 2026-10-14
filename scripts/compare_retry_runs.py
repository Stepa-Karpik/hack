"""Paired report comparison, preserving every field difference for review."""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prefix',choices=['orientation_retry','default_retry','date_validation'],required=True)
    args=parser.parse_args()
    before=json.loads((ROOT/f'artifacts/{args.prefix}_before.json').read_text(encoding='utf-8'))
    after=json.loads((ROOT/f'artifacts/{args.prefix}_after.json').read_text(encoding='utf-8'))
    key='degrees' if args.prefix=='orientation_retry' else 'condition'
    assert [(r['type'],r[key]) for r in before['rows']]==[(r['type'],r[key]) for r in after['rows']], 'Comparison cohorts differ'
    differences=[]
    for left,right in zip(before['rows'],after['rows']):
        if left['fields']!=right['fields'] or left.get('detected_type')!=right.get('detected_type'):
            differences.append({'type':left['type'],key:left[key],'before':left['fields'],'after':right['fields']})
    conditions={}
    for condition in sorted(set(r[key] for r in before['rows']),key=str):
        left=[r for r in before['rows'] if r[key]==condition]
        right=[r for r in after['rows'] if r[key]==condition]
        conditions[str(condition)]={'before_correct':sum(r['correct'] for r in left),'after_correct':sum(r['correct'] for r in right),
                                    'before_confident_wrong':sum(r['confident_wrong'] for r in left),'after_confident_wrong':sum(r['confident_wrong'] for r in right)}
    passed=all(c['after_correct']>=c['before_correct'] and c['after_confident_wrong']<=c['before_confident_wrong'] for c in conditions.values())
    report={'scope':after['scope'],'passed':passed,'unchanged_values_status_and_types':not differences,'differences':differences,
            'before_correct':before['correct'],'after_correct':after['correct'],'before_confident_wrong':before['confident_wrong'],
            'after_confident_wrong':after['confident_wrong'],'conditions':conditions,'groups':{}}
    if args.prefix=='orientation_retry':
        for name,predicate in [('upright',lambda r:r['degrees']==0),('rotated',lambda r:r['degrees']!=0)]:
            left=statistics.median(r['seconds'] for r in before['rows'] if predicate(r))
            right=statistics.median(r['seconds'] for r in after['rows'] if predicate(r))
            report['groups'][name]={'cases':sum(predicate(r) for r in before['rows']),'before_median_seconds':left,'after_median_seconds':right,'median_reduction_percent':100*(1-right/left)}
    (ROOT/f'artifacts/{args.prefix}_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['conditions','differences']},ensure_ascii=False,indent=2))
    if not passed:
        raise SystemExit(1)


if __name__=='__main__':
    main()
