"""Original narrative templates with word-level renderer supervision.

Values appear inside paragraphs and address blocks. Fields are never inferred
from OCR or organizer answers. This remains fictional shared-renderer data.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import ImageDraw, ImageFont
from scripts.unified.prepare_v2 import make as labeled, FONTS
from scripts.unified.prepare import TITLES
from scripts.unified.contract import KEYS, MARKS, parse


def make(seed,kind,split,fontfile,layout):
    image,target=labeled(seed,kind,split,fontfile,layout)
    draw=ImageDraw.Draw(image);draw.rectangle((0,0,1099,1230),fill='#fffefa')
    font=ImageFont.truetype(str(fontfile),28)
    small=ImageFont.truetype(str(fontfile),20)
    draw.text((65,35),'УЧЕБНЫЙ ОБРАЗЕЦ — ВЫМЫШЛЕННЫЕ СВЕДЕНИЯ',font=small,fill='#737373')
    bounds={}
    def value(key):
        text=target['fields'][key]
        if text is None:return [('________________',None)]
        if key.endswith(('start','end','date')):
            yy,mm,dd=text.split('-');text=f'{dd}.{mm}.{yy}'
        return [(text,key)]
    def flow(parts,y):
        x=65+(layout%2)*20;left=x
        for text,key in parts:
            for word in text.split():
                length=draw.textlength(word,font=font)
                if x+length>1035:
                    x=left;y+=39
                if y+36>1210:raise ValueError('Narrative overflow')
                draw.text((x,y),word,font=font,fill='#202020')
                if key:bounds.setdefault(key,[]).append(draw.textbbox((x,y),word,font=font))
                x+=length+draw.textlength(' ',font=font)
        return y+72
    text=lambda s:[(s,None)]
    y=110
    if kind=='study_certificate':
        y=flow(value('university'),y)
        y=flow(text(TITLES[kind]),y+20)
        y=flow(text('Справка №')+value('document_number')+text('от')+value('issue_date'),y)
        y=flow(text('Настоящая справка выдана студенту:')+value('student_name')+
               text('и подтверждает обучение по направлению')+value('program')+text('.'),y)
        y=flow(text('Форма обучения:')+value('study_form')+text('. Период обучения: с')+
               value('study_start')+text('по')+value('study_end')+text('.'),y)
        flow(text('Справка выдана для предъявления по месту требования.'),y)
    elif kind=='academic_leave_application':
        y=flow(text('Ректору учебного института «Технология»'),y)
        y=flow(text('От студента:')+value('student_name'),y)
        y=flow(text('Группа:')+value('group')+text('Курс:')+value('course'),y)
        y=flow(text(TITLES[kind]),y+25)
        y=flow(text('Прошу предоставить академический отпуск')+value('leave_reason')+
               text('на период с')+value('leave_start')+text('по')+value('leave_end')+text('.'),y)
        flow(text('Дата подачи заявления:')+value('application_date'),y+25)
    else:
        y=flow(value('organization'),y)
        y=flow(text(TITLES[kind]),y+20)
        y=flow(text('Справка №')+value('document_number'),y)
        y=flow(text('Настоящим подтверждаем, что студент')+value('student_name')+
               text('прошёл практику в указанной организации с')+value('internship_start')+
               text('по')+value('internship_end')+text('.'),y)
        y=flow(text('Руководитель практики:')+value('supervisor_name'),y)
        y=flow(text('Оценка по итогам практики:')+value('grade'),y)
        flow(text('Дата выдачи справки:')+value('issue_date'),y+25)
    for key in KEYS[kind]:
        if key in MARKS:continue
        parts=bounds.get(key,[])
        if target['fields'][key] is None:
            target['boxes'][key]=None
        else:
            if not parts:raise ValueError(f'Value not printed: {key}')
            box=[min(b[0] for b in parts),min(b[1] for b in parts),max(b[2] for b in parts),max(b[3] for b in parts)]
            target['boxes'][key]=[round(v/d*1000) for v,d in zip(box,(1100,1480,1100,1480))]
    parse(json.dumps(target));return image,target


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--font-dir',type=Path,required=True);p.add_argument('--train',type=int,default=180)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh immutable dataset directory')
    args.output.mkdir(parents=True)
    manifest={'source':'original fictional narrative templates; renderer word-level boxes',
              'license':'AGPL-3.0 project code; fonts not redistributed',
              'scope':'synthetic shared renderer and content pools; no independent real accuracy',
              'seed':202610123,'splits':{}}
    for split,count,offset in [('train',args.train,0),('val',12,100000),('test',12,200000)]:
        directory=args.output/split;directory.mkdir();rows=[]
        for i in range(count):
            font=args.font_dir/FONTS[split][i%len(FONTS[split])]
            image,target=make(202610123+offset+i,list(KEYS)[i%3],split,font,i%6)
            file=directory/f'{i:04d}.png';image.save(file)
            rows.append({'image':file.relative_to(args.output).as_posix(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                         'target':target,'font':font.name,'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),'layout':i%6})
        file=args.output/f'{split}.jsonl';file.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
        manifest['splits'][split]={'count':count,'records_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'fonts':FONTS[split]}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':main()
