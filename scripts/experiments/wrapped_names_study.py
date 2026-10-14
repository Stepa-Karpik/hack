"""Fresh synthetic printed layout diagnosis, no inference access to expected values."""
import argparse,hashlib,json,sys
from pathlib import Path
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.participantkit.service import analyze_document
from scripts.participantkit.labeled_fields import candidates


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output)
    if output.exists():raise FileExistsError(output)
    cases=[
        ('inline',['Название вуза: Университет «Лесные горизонты»'],'Университет «Лесные горизонты»'),
        ('wrap_two',['Название вуза: Университет','«Приозёрные технологии»'],'Университет «Приозёрные технологии»'),
        ('wrap_three',['Название вуза: Институт','«Северные исследовательские','системы»'],'Институт «Северные исследовательские системы»'),
        ('empty_next_label',['Название вуза:','Направление подготовки: 09.03.02 Информационные системы'],'не найдено'),
        ('empty_footer',['Название вуза:','УЧЕБНЫЙ МАКЕТ. Все сведения вымышлены'],'не найдено'),
        ('wrap_next_label',['Название вуза: Университет «Новые','маршруты»','Форма обучения: очная'],'Университет «Новые маршруты»')]
    rows=[]
    for fontname in ['arial.ttf','times.ttf']:
        fontpath=Path('C:/Windows/Fonts')/fontname;font=ImageFont.truetype(str(fontpath),28)
        for case,texts,expected in cases:
            image=Image.new('RGB',(1400,850),'white');draw=ImageDraw.Draw(image)
            printed=['СПРАВКА ОБ ОБУЧЕНИИ','ФИО студента: Орлова Дарья Игоревна']+texts
            if not any(t.startswith('Направление подготовки:') for t in texts):printed.append('Направление подготовки: 09.03.02 Информационные системы')
            if not any(t.startswith('Форма обучения:') for t in texts):printed.append('Форма обучения: очная')
            printed+=['Начало периода обучения: 01.09.2025','Окончание периода обучения: 30.06.2029','Номер справки: 527-18','Дата выдачи: 09.10.2026']
            oracle=[]
            for i,text in enumerate(printed):
                position=(60,35+i*48);draw.text(position,text,font=font,fill='black')
                oracle.append({'text':text,'bbox':list(draw.textbbox(position,text,font=font)),'page':0,'confidence':1.0})
            stream=BytesIO();image.save(stream,format='PNG');data=stream.getvalue()
            # Expected values are used only below, after complete inference.
            result=analyze_document(data,'layout.png','study_certificate',[],document_id='layout')
            actual=result['result']['fields']['university'];bindings=candidates(oracle).get('university',[])
            rows.append({'font':fontname,'font_sha256':hashlib.sha256(fontpath.read_bytes()).hexdigest(),'case':case,'printed':printed,'image_sha256':hashlib.sha256(data).hexdigest(),'expected':expected,'actual':actual,'exact':actual==expected,'oracle_label_candidates':bindings,'runtime':result})
            print(fontname,case,actual==expected,flush=True)
    report={'scope':'Twelve fresh synthetic clean printed full-service uploads, six layouts in two Windows fonts. After viewing development, not independent real accuracy. No training or deployment change. Oracle lines are rendered-text diagnosis only, never fed to inference. Fonts/images not distributed; generator and hashes retained.','rows':rows,'exact':sum(r['exact'] for r in rows),'total':len(rows),'negative_false_nonempty':sum(r['expected']=='не найдено' and r['actual']!='не найдено' for r in rows)}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda v:v.tolist()),encoding='utf-8')
    print(report['exact'],report['total'],report['negative_false_nonempty'])


if __name__=='__main__':main()
