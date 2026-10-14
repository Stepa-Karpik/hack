"""Full app shadow qualification without reading organizer reference answers."""
import argparse,hashlib,json,sys
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.experiments.wrapped_names_image_shadow import analyze_shadow


def main():
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    rows=[]
    def run(group,data,filename,kind,questions,identifier,expected=None,previous=None):
        shadow=analyze_shadow(data,filename,kind,questions,document_id=identifier)
        before=shadow['before'];after=shadow['after']
        rows.append({'group':group,'document_id':identifier,'input_sha256':hashlib.sha256(data).hexdigest(),'expected_university':expected,
            'baseline_matches_stored_v7':before==previous if previous is not None else None,
            'result_unchanged':before==after,'before_exact':before['fields'].get('university')==expected if expected is not None else None,
            'after_exact':after['fields'].get('university')==expected if expected is not None else None,'shadow':shadow})
        print(group,identifier,before==after,shadow['proposal']['reason'],flush=True)
    manifest=json.loads((args.kit/'documents.json').read_text(encoding='utf-8'));qs=json.loads((args.kit/'questions.json').read_text(encoding='utf-8'))
    for mode in ['image','pdf']:
        stored=json.loads((ROOT/f'artifacts/participant_service_v7_{mode}_full.json').read_text(encoding='utf-8'))['documents']
        previous={x['document_id']:x for x in stored}
        for record in manifest:
            path=(args.kit/record[mode]).resolve()
            if not path.is_relative_to(args.kit.resolve()):raise ValueError('Outside kit')
            questions=[{k:q[k] for k in ['question_id','question']} for q in qs if q['document_id']==record['document_id']]
            run('kit_'+mode,path.read_bytes(),path.name,record['document_type'],questions,record['document_id'],previous=previous[record['document_id']])
    own=ROOT.parent/'Реалистичные-документы'
    for index,path in enumerate(sorted(list(own.glob('*.pdf'))+list(own.glob('*.jpg')))):
        number=int(path.name[:2]);kind='academic_leave_application' if number in [3,4] else 'internship_certificate' if number in [5,6,9] else 'study_certificate'
        run('own',path.read_bytes(),path.name,kind,[{'question_id':'date','question':'Какова дата выдачи?'}],f'own-{index}')
    controls=[('wrap',['Название вуза: Университет','«Лунные вычисления»'],'Университет «Лунные вычисления»'),
      ('closed',['Название вуза: Университет «Тихий залив»','Просьба сверить номер справки'],'Университет «Тихий залив»'),
      ('blank_note',['Название вуза:','Примечание: Университет «Лазурный остров»'],'не найдено'),
      ('duplicate',['Название вуза: Университет «Медный склон»','Название вуза: Институт «Ледяной лес»'],'не найдено')]
    for fontname in ['arial.ttf','calibri.ttf']:
        fontpath=Path('C:/Windows/Fonts')/fontname;font=ImageFont.truetype(str(fontpath),28)
        for name,texts,expected in controls:
            image=Image.new('RGB',(1400,850),'white');draw=ImageDraw.Draw(image)
            printed=['СПРАВКА ОБ ОБУЧЕНИИ','ФИО студента: Павлова Мария Андреевна']+texts+['Форма обучения: очная','Начало периода обучения: 01.09.2025','Окончание периода обучения: 30.06.2029','Номер справки: 721-20','Дата выдачи: 11.10.2026']
            for i,text in enumerate(printed):draw.text((60,35+i*48),text,font=font,fill='black')
            output=BytesIO();image.save(output,format='PNG')
            run('fresh',output.getvalue(),'fresh.png','study_certificate',[],fontname+':'+name,expected=expected)
            rows[-1].update(printed=printed,font=fontname,font_sha256=hashlib.sha256(fontpath.read_bytes()).hexdigest())
    groups={g:{'total':sum(x['group']==g for x in rows),'changed':sum(not x['result_unchanged'] for x in rows if x['group']==g),'attempted':sum(x['shadow']['proposal']['attempted'] for x in rows if x['group']==g),'baseline_stored_mismatch':sum(x['baseline_matches_stored_v7'] is False for x in rows if x['group']==g)} for g in ['kit_image','kit_pdf','own','fresh']}
    fresh=[r for r in rows if r['group']=='fresh'];groups['fresh'].update(before_exact=sum(r['before_exact'] for r in fresh),after_exact=sum(r['after_exact'] for r in fresh),changed_wrong=sum(not r['after_exact'] and not r['result_unchanged'] for r in fresh))
    report={'scope':'Full unchanged local OCR/service plus separate guarded image reread shadow. Kit PNG/PDF are two views of same 30 viewed development documents. Own viewed synthetic pack and eight fresh clean controls, not independent real accuracy. No deployment/training/reference access.','groups':groups,'rows':rows}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda v:v.tolist()),encoding='utf-8');print(json.dumps(groups))


if __name__=='__main__':main()
