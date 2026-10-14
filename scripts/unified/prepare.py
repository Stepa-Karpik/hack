"""Fresh fictitious single-page documents with renderer-grounded values and boxes.

No participant kit, saved predictions, original documents or reference answers.
Fonts are used locally and are never distributed. Text layouts are disjoint by split.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from scripts.unified.contract import KEYS, MARKS
from scripts.participantkit.format_v1 import LABELS

TITLES = {'study_certificate': 'СПРАВКА ОБ ОБУЧЕНИИ',
          'academic_leave_application': 'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК',
          'internship_certificate': 'СПРАВКА О ПРОХОЖДЕНИИ ПРАКТИКИ'}


def make(seed, kind, layout, fontfile, overrides=None, empty_keys=(), marks=None):
    rng = random.Random(seed)
    image = Image.new('RGB', (1240, 1754), '#fffefa')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(fontfile), 27)
    small = ImageFont.truetype(str(fontfile), 22)
    title = ImageFont.truetype(str(fontfile), 29)
    draw.text((90, 70), 'УЧЕБНЫЙ ОБРАЗЕЦ • ВЫМЫШЛЕННЫЕ ДАННЫЕ', font=small, fill='#777777')
    draw.text((90, 120), 'Институт информационных технологий «Горизонт»', font=font, fill='#202020')
    draw.line((90, 170, 1150, 170), fill='#999999', width=1)
    draw.text((90, 230), TITLES[kind], font=title, fill='black')
    names = ['Александр', 'Денис', 'Мария', 'Николай', 'Анна', 'Вера']
    surnames = ['Родников', 'Луговой', 'Мельников', 'Крылов', 'Светлов', 'Дубров']
    student = f'{rng.choice(surnames)} {rng.choice(names)} {rng.choice(["Андреевич", "Сергеевич", "Ильинична"])}'
    day, month = rng.randint(1, 28), rng.randint(1, 12)
    values = {'student_name': student, 'university': rng.choice(['Институт «Северный берег»', 'Университет «Новая орбита»', 'Институт «Цифровой горизонт»']),
              'program': rng.choice(['09.03.01 Информатика и вычислительная техника', '01.03.02 Прикладная математика', '38.03.01 Экономика']),
              'study_form': rng.choice(['очная', 'заочная', 'очно-заочная']),
              'study_start': f'202{rng.randint(1,4)}-09-01', 'study_end': '2027-06-30',
              'document_number': f'{rng.choice(["ИТ", "СП", "ПР"])}-{rng.randint(100,99999)}',
              'issue_date': f'2026-{month:02d}-{day:02d}', 'application_date': f'2026-{month:02d}-{day:02d}',
              'group': f'{rng.choice(["ИВТ", "ПМ", "ЭК"])}-{rng.randint(11,49)}', 'course': str(rng.randint(1,4)),
              'leave_reason': rng.choice(['по семейным обстоятельствам', 'по состоянию здоровья', 'в связи с уходом за ребёнком']),
              'leave_start': '2026-10-20', 'leave_end': '2027-04-20',
              'organization': rng.choice(['ООО «Полярные системы»', 'АО «Новые технологии»', 'ООО «Умный контур»']),
              'internship_start': '2026-06-01', 'internship_end': '2026-07-15',
              'supervisor_name': f'{rng.choice(surnames)} {rng.choice(names)} Сергеевич',
              'grade': rng.choice(['отлично', 'хорошо', 'удовлетворительно'])}
    overrides = overrides or {}
    values.update(overrides)
    keys = [key for key in KEYS[kind] if key not in MARKS]
    if layout % 3 == 1:
        rng.shuffle(keys)
    fields, boxes = {}, {}
    def box(bounds):
        return [round(v/d*1000) for v, d in zip(bounds, (1240,1754,1240,1754))]
    y = 350
    for key in keys:
        random_missing = rng.random() < .16
        missing = key in empty_keys or (key not in overrides and random_missing)
        fields[key] = None if missing else values[key]
        label = LABELS[key] + ': '
        # Some missing fields retain a caption; others are entirely absent.
        if missing and rng.random() < .5:
            boxes[key] = None
            continue
        x = 90 + (layout % 2)*30
        draw.text((x, y), label, font=font, fill='black')
        vx = x + draw.textlength(label, font=font)
        text = '' if missing else values[key]
        if key.endswith(('start','end','date')) and text:
            yy, mm, dd = text.split('-'); text = f'{dd}.{mm}.{yy}'
        if layout % 4 == 2 or vx + draw.textlength(text, font=font) > 1140:
            vx, vy = x+30, y+39
            y += 45
        else:
            vy = y
        draw.text((vx,vy), text or '________________', font=font, fill='black')
        boxes[key] = box(draw.textbbox((vx,vy), text, font=font)) if text else None
        y += 88
    draw.text((95, 1395), 'Подпись: ____________________', font=font, fill='black')
    draw.text((840, 1395), 'М.П.', font=font, fill='black')
    for key in KEYS[kind]:
        if key not in MARKS:
            continue
        present = rng.random() < .5
        if marks is not None and key in marks:
            present = marks[key]
        fields[key] = present; boxes[key] = None
        if not present:
            continue
        if key == 'signature_present':
            bounds = (235, 1470, 535, 1550)
            points = [(235+i*10, 1510+rng.uniform(-35,35)) for i in range(31)]
            draw.line(points, fill='#173963', width=3)
            draw.arc((260,1470,400,1540), 15, 330, fill='#173963', width=3)
        else:
            bounds = (850,1460,1030,1640)
            draw.ellipse(bounds, outline='#264b92', width=4)
            draw.ellipse((862,1472,1018,1628), outline='#264b92', width=2)
            draw.text((874,1525), 'УЧЕБНАЯ', font=small, fill='#264b92')
            draw.text((884,1555), 'ПЕЧАТЬ', font=small, fill='#264b92')
        boxes[key] = box(bounds)
    draw.text((90,1690), 'Для проверки программного обеспечения. Не имеет юридической силы.', font=small, fill='#777777')
    return image, {'document_type': kind, 'fields': {k:fields[k] for k in KEYS[kind]},
                   'boxes': {k:boxes[k] for k in KEYS[kind]}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    parser.add_argument('--train', type=int, default=72)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a fresh output directory; datasets are immutable')
    args.output.mkdir(parents=True)
    fonts = {'train': ['arial.ttf','times.ttf'], 'val': ['calibri.ttf'], 'test': ['verdana.ttf']}
    metadata = {'source':'original renderer; fictional content', 'license':'AGPL-3.0 project code; local fonts not redistributed',
                'seed':202610120, 'scope':'synthetic development pilot; not real-world accuracy', 'splits':{}}
    for split, count, layouts, offset in [('train',args.train,range(0,8),0),('val',12,range(8,10),100000),('test',12,range(10,12),200000)]:
        rows = []; directory = args.output/split; directory.mkdir()
        for i in range(count):
            fontfile = args.font_dir/fonts[split][i%len(fonts[split])]
            image, target = make(202610120+offset+i,list(KEYS)[i%3],list(layouts)[i%len(layouts)],fontfile)
            file = directory/f'{i:04d}.png'; image.save(file)
            rows.append({'image':file.relative_to(args.output).as_posix(), 'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                         'target':target, 'layout':list(layouts)[i%len(layouts)], 'font':fontfile.name,
                         'font_sha256':hashlib.sha256(fontfile.read_bytes()).hexdigest()})
        (args.output/f'{split}.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
        metadata['splits'][split] = {'count':count,'layouts':list(layouts),'fonts':fonts[split]}
    (args.output/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
