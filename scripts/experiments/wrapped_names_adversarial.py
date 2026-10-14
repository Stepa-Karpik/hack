"""New layouts evaluated with unchanged experimental candidate v1."""
import argparse,hashlib,json,sys
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.participantkit.service import analyze_document
from scripts.experiments.wrapped_names_reread import propose


def cases():
    return [
      ('new_wrap',[(60,135,'Название вуза: Университет'),(60,183,'«Облачные механизмы»')],'Университет «Облачные механизмы»'),
      ('right_column',[(60,135,'Название вуза: Университет'),(60,183,'«Речные мастерские»'),(850,183,'Срок действия'),(850,231,'один учебный год')],'Университет «Речные мастерские»'),
      ('duplicate_labels',[(60,135,'Название вуза: Университет «Остров»'),(60,183,'Название вуза: Институт «Орион»')],'не найдено'),
      ('blank_borrowed_name',[(60,135,'Название вуза:'),(60,183,'Университет «Тёплый ветер»')],'не найдено'),
      ('closed_then_prose',[(60,135,'Название вуза: Университет «Вектор»'),(60,183,'Просьба сверить номер справки')],'Университет «Вектор»'),
      ('ambiguous_two_parts',[(60,135,'Название вуза: Университет «Маяк'),(60,183,'северный»'),(130,183,'южный»')],'не найдено'),
      ('next_label_stop',[(60,135,'Название вуза:'),(60,183,'Направление подготовки: 09.03.02 Системы')],'не найдено'),
      ('new_three_rows',[(60,135,'Название вуза: Институт'),(60,183,'«Западные вычислительные'),(60,231,'исследования»')],'Институт «Западные вычислительные исследования»')]


def render(layout,fontname):
    path=Path('C:/Windows/Fonts')/fontname;font=ImageFont.truetype(str(path),28)
    image=Image.new('RGB',(1600,850),'white');draw=ImageDraw.Draw(image)
    printed=[(60,35,'СПРАВКА ОБ ОБУЧЕНИИ'),(60,83,'ФИО студента: Никитина Елена Сергеевна')]+layout
    printed += [(60,330,'Форма обучения: очная'),(60,378,'Начало периода обучения: 01.09.2025'),(60,426,'Окончание периода обучения: 30.06.2029'),(60,474,'Номер справки: 624-19'),(60,522,'Дата выдачи: 10.10.2026')]
    for x,y,text in printed:draw.text((x,y),text,font=font,fill='black')
    return image,printed,hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_cases():
    valid=[c for c in cases() if c[0] not in {'blank_borrowed_name','ambiguous_two_parts'}]
    valid += [
      ('blank_right_callout',[(60,135,'Название вуза:'),(850,183,'Справочно: Университет «Зелёный берег»')],'не найдено'),
      ('blank_labeled_note',[(60,135,'Название вуза:'),(60,183,'Примечание: Университет «Восточный путь»')],'не найдено')]
    return valid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--reviewed',action='store_true');args=parser.parse_args();out=Path(args.output)
    if out.exists():raise FileExistsError(out)
    rows=[]
    for fontname in ['calibri.ttf','verdana.ttf']:
        for case,layout,expected in (reviewed_cases() if args.reviewed else cases()):
            image,printed,fontsha=render(layout,fontname);buffer=BytesIO();image.save(buffer,format='PNG');data=buffer.getvalue()
            runtime=analyze_document(data,'new-layout.png','study_certificate',[],document_id='new-layout')
            proposal=propose(image,runtime['ocr']['lines'])
            before=runtime['result']['fields']['university'];after=proposal['accepted'] or before
            rows.append({'font':fontname,'font_sha256':fontsha,'case':case,'printed':printed,'image_sha256':hashlib.sha256(data).hexdigest(),'expected':expected,'before':before,'after':after,'baseline_exact':before==expected,'candidate_exact':after==expected,'changed_wrong':after!=before and after!=expected,'proposal_false_nonempty':expected=='не найдено' and proposal['accepted'] is not None,'proposal':proposal,'runtime':runtime})
            print(fontname,case,before==expected,after==expected,proposal['accepted'] is not None,flush=True)
    report={'scope':'Sixteen synthetic layouts, eight cases in two additional local fonts. Baseline full service and unchanged offline v1 candidate. Viewed development, not independent real accuracy. Original mode includes ambiguous author-intent truth and overlapped text: raw counts are not valid accuracy. Reviewed mode excludes those and adds two explicit note/callout negatives. No training/deployment.','reviewed':args.reviewed,'rows':rows,'total':len(rows),'baseline_exact':sum(r['baseline_exact'] for r in rows),'candidate_exact':sum(r['candidate_exact'] for r in rows),'changed_wrong':sum(r['changed_wrong'] for r in rows),'proposal_false_nonempty':sum(r['proposal_false_nonempty'] for r in rows)}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda v:v.tolist()),encoding='utf-8');print({k:v for k,v in report.items() if k!='rows'})


if __name__=='__main__':main()
