"""Evaluation-only character and literal diagnostics. Not imported by inference."""
import argparse,json,re,unicodedata
from pathlib import Path

def normalized(text):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFC',text)).strip()

def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=current
    return previous[-1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--controls',type=Path,required=True)
    p.add_argument('--predictions',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise ValueError('Fresh evaluation report required')
    expected={r['sha256']:r for r in json.loads(args.controls.read_text(encoding='utf-8'))['rows']}
    result=json.loads(args.predictions.read_text(encoding='utf-8'))
    if not result['complete']:raise ValueError('Incomplete prediction diagnostic')
    seen=set();rows=[];edits=chars=found=total=0
    for r in result['rows']:
        sha=r['input_sha256']
        if sha in seen:raise ValueError('Duplicate input in diagnostic')
        seen.add(sha);target=expected[sha];text=normalized(r['raw'])
        truth=normalized(' '.join(target['expected_lines']));d=distance(truth,text)
        exact=[normalized(line) in text for line in target['expected_lines']]
        edits+=d;chars+=len(truth);found+=sum(exact);total+=len(exact)
        rows.append({'image':target['image'],'sha256':sha,'edit_distance':d,'reference_chars':len(truth),
                     'literal_lines_found':sum(exact),'literal_lines_total':len(exact),'exact_flags':exact,
                     'token_budget_reached':r.get('token_budget_reached',False)})
    args.output.write_text(json.dumps({'scope':'Viewed synthetic literal OCR only, not field/mark/app accuracy',
        'normalization':'Unicode NFC and whitespace only; accents, punctuation, case and digits preserved',
        'literal_metric':'Expected full line appears verbatim; extra output penalized by whole-text CER',
        'counts':{'pages':len(rows),'edit_distance':edits,'reference_chars':chars,'cer':edits/chars,
                  'literal_lines_found':found,'literal_lines_total':total},'rows':rows,'promoted':False},indent=2),encoding='utf-8')
    print('CER',round(edits/chars,4),'literal lines',found,'/',total)

if __name__=='__main__':main()
