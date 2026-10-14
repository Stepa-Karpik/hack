"""First-pass existing V21 inference; no reference labels loaded here."""
from pathlib import Path
import sys,json,hashlib,argparse
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.pipeline import analyze,ANALYSIS_VERSION
from format_v1 import KINDS,fields_from_v21,validate,answer

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kit',type=Path,required=True)
    args=parser.parse_args();pack=args.kit
    config=json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))
    manifest=json.loads((pack/'documents.json').read_text(encoding='utf-8'))
    questions=json.loads((pack/'questions.json').read_text(encoding='utf-8'))
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')}
    assert source==json.loads((ROOT/'artifacts/participant_kit_v1_intake.json').read_text(encoding='utf-8'))['runtime_sha256_before_target_tuning']
    assert ANALYSIS_VERSION=='2026-10-11-official-v21'
    freeze={'version':ANALYSIS_VERSION,'runtime_sha256':source,
        'adapter_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
        'policy_sha256':hashlib.sha256((ROOT/'configs/participant_v1.json').read_bytes()).hexdigest(),
        'scope':'First-pass V21 existing extraction, known manual types, new contract/policy adapter only. Labels not used in inference; raw uncertain literal values exported, conflicts missing, visual raw bool prediction. PNG/PDF paired presentations, not60independent examples. Open synthetic target kit, not real accuracy.'}
    path=ROOT/'artifacts/participant_v21_initial_freeze.json'
    if path.exists():raise RuntimeError('Do not overwrite initial baseline freeze')
    path.write_text(json.dumps(freeze,ensure_ascii=False,indent=2),encoding='utf-8')
    for variant in ['image','pdf']:
        results={'version':'1.0','documents':[]};raw=[]
        for record in manifest:
            p=(pack/record[variant]).resolve();assert p.is_relative_to(pack.resolve())
            data=p.read_bytes();_,analysis=analyze(data,p.name,document_type=KINDS[record['document_type']])
            fields=fields_from_v21(analysis,record['document_type'],config);validation=validate(fields,record['document_type'],config)
            answers=[{'question_id':q['question_id'],**answer(q['question'],fields,validation,config)} for q in questions if q['document_id']==record['document_id']]
            results['documents'].append({'document_id':record['document_id'],'document_type':record['document_type'],'fields':fields,'validation':validation,'answers':answers})
            raw.append({'document_id':record['document_id'],'input_sha256':hashlib.sha256(data).hexdigest(),'analysis':analysis})
            for name,value in [(f'participant_v21_initial_{variant}_results.json',results),(f'participant_v21_initial_{variant}_raw.json',{'scope':freeze['scope'],'runtime_sha256':source,'rows':raw})]:
                (ROOT/'artifacts'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=lambda x:x.tolist()),encoding='utf-8')
            print(variant,record['document_id'],len(validation['missing_fields']),'missing',round(analysis['seconds'],2),'s',flush=True)
        assert source=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')}

if __name__=='__main__':main()
