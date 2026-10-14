"""Preserve prior correct confirmed fields on exactly the same official inputs."""
import argparse,json
from pathlib import Path


def compare(before,after):
    old={row['id']:row for row in before['rows']};new={row['id']:row for row in after['rows']}
    failures=[]
    if old.keys()!=new.keys():failures.append('Different input identities')
    for key in old.keys() & new.keys():
        a,b=old[key],new[key]
        if a['input_sha256']!=b['input_sha256']:failures.append(key+': input changed')
        if a['analysis']['type']==a['expected_type'] and b['analysis']['type']!=b['expected_type']:failures.append(key+': correct type lost')
        current={f['field']:f for f in b['comparisons']}
        for field in a['comparisons']:
            if field.get('correct') and field['observed']['status']=='found':
                candidate=current.get(field['field'],{})
                if not candidate.get('correct') or candidate['observed']['status']!='found':failures.append(key+': confirmed '+field['field']+' lost')
        for field in b['comparisons']:
            previous=next((f for f in a['comparisons'] if f['field']==field['field']),{})
            if field.get('false_found') and not previous.get('false_found'):failures.append(key+': newly invented '+field['field'])
            if field.get('correct') is False and field['observed']['status']=='found' and not (previous.get('correct') is False and previous['observed']['status']=='found'):failures.append(key+': newly confirmed wrong '+field['field'])
    if after['summary']['false_confirmed_marks']>before['summary']['false_confirmed_marks']:failures.append('New false confirmed visual marks')
    return {'passed':not failures,'failures':failures,'before':before['summary'],'after':after['summary'],
            'scope':'Same viewed development inputs only; field-by-field preservation, no timing claim or independent accuracy estimate'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--before',type=Path,required=True);parser.add_argument('--after',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=compare(json.loads(args.before.read_text(encoding='utf-8')),json.loads(args.after.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)
