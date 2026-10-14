"""Expanded original renderer. Split content and fonts never cross partitions.

Fictional marks are visual training controls, not examples of authentic marks.
No benchmark references, external documents or model predictions are read.
"""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from scripts.unified.contract import KEYS, MARKS, parse
from scripts.unified.prepare import TITLES
from scripts.participantkit.format_v1 import LABELS

CONTENT = {
    'train': (['Белов', 'Зайцев', 'Соколов', 'Орлов', 'Титов', 'Громов', 'Волков', 'Фомин'],
              ['Иван', 'Павел', 'Олег', 'Михаил', 'Роман', 'Кирилл'],
              ['Север', 'Вектор', 'Спектр', 'Искра', 'Рубеж', 'Исток']),
    'val': (['Калинин', 'Быков', 'Савин'], ['Артём', 'Юрий', 'Степан'],
            ['Меридиан', 'Каскад', 'Контур']),
    'test': (['Авдеев', 'Носов', 'Ершов'], ['Вадим', 'Егор', 'Глеб'],
             ['Орион', 'Импульс', 'Альтаир']),
}
FONTS = {'train': ['arial.ttf', 'times.ttf', 'calibri.ttf'],
         'val': ['georgia.ttf'], 'test': ['verdana.ttf']}


def make(seed, kind, split, fontfile, layout, empty_keys=(), marks=None):
    rng = random.Random(seed)
    width, height = 1100, 1480
    image = Image.new('RGB', (width, height), '#fffefa')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(fontfile), 28)
    small = ImageFont.truetype(str(fontfile), 20)
    surnames, names, organizations = CONTENT[split]
    name = lambda: f'{rng.choice(surnames)} {rng.choice(names)} {rng.choice(["Павлович", "Олегович", "Иванович"])}'
    date = lambda year: f'{year}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}'
    fields = {'student_name': name(), 'university': f'Университет «{rng.choice(organizations)}»',
              'program': rng.choice(['09.03.02 Информационные системы и технологии',
                                     '27.03.01 Стандартизация и метрология',
                                     '38.03.02 Менеджмент', '10.03.01 Информационная безопасность']),
              'study_form': rng.choice(['очная', 'заочная', 'очно-заочная']),
              'study_start': date(2023), 'study_end': date(2028),
              'document_number': f'{rng.choice(["АБ", "ВС", "ТК"])}-{rng.randint(1000,99999)}',
              'issue_date': date(2026), 'application_date': date(2026),
              'group': f'{rng.choice(["КТ", "ИБ", "МН"])}-{rng.randint(10,99)}',
              'course': str(rng.randint(1,5)),
              'leave_reason': rng.choice(['по семейным обстоятельствам', 'по состоянию здоровья',
                                          'в связи с уходом за ребёнком']),
              'leave_start': date(2026), 'leave_end': date(2027),
              'organization': f'{rng.choice(["ООО", "АО"])} «{rng.choice(organizations)} Лаб»',
              'internship_start': date(2026), 'internship_end': date(2026),
              'supervisor_name': name(), 'grade': rng.choice(['отлично', 'хорошо', 'удовлетворительно'])}
    draw.text((65, 35), 'ВЫМЫШЛЕННЫЙ УЧЕБНЫЙ ОБРАЗЕЦ', font=small, fill='#737373')
    # Deliberately unrelated header name: never a substitute for a blank student.
    draw.text((65, 83), 'Учебный центр «Технология»', font=font, fill='#343434')
    draw.text((65, 142), TITLES[kind], font=font, fill='black')
    keys = [k for k in KEYS[kind] if k not in MARKS]
    if layout % 2:
        rng.shuffle(keys)
    boxes = {}
    y = 228
    def normalized(bounds):
        return [round(v / d * 1000) for v, d in zip(bounds, (width,height,width,height))]
    for key in keys:
        missing = key in empty_keys or rng.random() < .22
        if missing:
            fields[key] = None
        text = fields[key]
        if text and key.endswith(('date', 'start', 'end')):
            yy, mm, dd = text.split('-'); text = f'{dd}.{mm}.{yy}'
        label = LABELS[key] + ':'
        x = 65 + (layout % 3) * 12
        draw.text((x, y), label, font=font, fill='black')
        vx = x + draw.textlength(label + ' ', font=font)
        vy = y
        if layout % 3 == 1 or vx > 640:
            vx, vy = x + 26, y + 37
        available = 1035 - vx
        lines = ['']
        for word in (text or '________________').split():
            trial = (lines[-1] + ' ' + word).strip()
            if lines[-1] and draw.textlength(trial, font=font) > available:
                lines.append(word)
            else:
                lines[-1] = trial
        bounds = []
        for j, line in enumerate(lines):
            position = (vx, vy + j * 36)
            draw.text(position, line, font=font, fill='black')
            bounds.append(draw.textbbox(position, line, font=font))
        boxes[key] = normalized((min(b[0] for b in bounds), min(b[1] for b in bounds),
                                 max(b[2] for b in bounds), max(b[3] for b in bounds))) if text else None
        if layout % 3 == 2:
            draw.line((x, vy+len(lines)*36+8, 1035, vy+len(lines)*36+8), fill='#b4b4b4')
        y = vy + len(lines) * 36 + 25
    if y > 1230:
        raise ValueError('Renderer overflow: never save clipped training content')
    sx = rng.randint(170, 430)
    sy = rng.randint(max(1260, y+20), 1290)
    draw.text((70, sy-40), 'Подпись: __________________', font=font, fill='black')
    draw.text((810, sy-40), 'М.П.', font=font, fill='black')
    for key in KEYS[kind]:
        if key not in MARKS:
            continue
        present = bool(rng.getrandbits(1))
        if marks is not None and key in marks:
            present = marks[key]
            if type(present) is not bool:raise ValueError('Mark override must be boolean')
        fields[key] = present; boxes[key] = None
        if not present:
            continue
        color = rng.choice(['#153b6c', '#252525', '#315892'])
        if key == 'signature_present':
            # Continuous varied pen traces; these are synthetic, not real signatures.
            phase = rng.random()*math.pi
            points = [(sx+i*2, sy+int(19*math.sin(i*.23+phase)+11*math.sin(i*.57))) for i in range(125)]
            draw.line(points, fill=color, width=rng.choice([2,3,4]))
            bounds = (sx-2, sy-33, sx+252, sy+33)
            draw.line((sx+10, sy+30, sx+240, sy+13), fill=color, width=2)
        else:
            cx = rng.randint(820,890); cy = sy+30
            bounds = (cx-78,cy-78,cx+78,cy+78)
            draw.ellipse(bounds, outline=color, width=3)
            draw.ellipse((cx-69,cy-69,cx+69,cy+69), outline=color, width=2)
            draw.text((cx-44,cy-24), 'ОБРАЗЕЦ', font=small, fill=color)
            draw.text((cx-42,cy+6), 'ПЕЧАТЬ', font=small, fill=color)
        boxes[key] = normalized(bounds)
    draw.text((65, 1435), 'Тестовый макет. Не имеет юридической силы.', font=small, fill='#737373')
    # Photometric transforms preserve geometry. No real-camera accuracy claim.
    if seed % 4 == 0:
        image = image.filter(ImageFilter.GaussianBlur(.4))
    if seed % 4 == 1:
        image = ImageEnhance.Contrast(image).enhance(.72)
    target = {'document_type':kind, 'fields':{k:fields[k] for k in KEYS[kind]},
              'boxes':{k:boxes[k] for k in KEYS[kind]}}
    parse(json.dumps(target))
    return image, target


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--font-dir',type=Path,required=True); p.add_argument('--train',type=int,default=240)
    args=p.parse_args()
    if args.output.exists(): raise ValueError('Dataset must have a fresh immutable directory')
    args.output.mkdir(parents=True)
    manifest={'source':'original expanded fictional renderer', 'license':'AGPL-3.0 project code; fonts not redistributed',
              'seed':202610121, 'scope':'synthetic split-disjoint content/fonts; shared renderer; not independent real data',
              'augmentation':['Gaussian blur radius .4 on one quarter', 'contrast .72 on one quarter'], 'splits':{}}
    for split,count,offset in [('train',args.train,0),('val',12,100000),('test',12,200000)]:
        directory=args.output/split; directory.mkdir(); records=[]
        for i in range(count):
            font=args.font_dir/FONTS[split][i%len(FONTS[split])]
            image,target=make(202610121+offset+i,list(KEYS)[i%3],split,font,i%6,
                              empty_keys=('student_name',) if i%8==0 else ())
            file=directory/f'{i:04d}.png'; image.save(file)
            records.append({'image':file.relative_to(args.output).as_posix(),
                            'sha256':hashlib.sha256(file.read_bytes()).hexdigest(), 'target':target,
                            'font':font.name,'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),'layout':i%6})
        (args.output/f'{split}.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records),encoding='utf-8')
        manifest['splits'][split]={'count':count,'fonts':FONTS[split],'content':CONTENT[split],
                                 'records_sha256':hashlib.sha256((args.output/f'{split}.jsonl').read_bytes()).hexdigest()}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__': main()
