"""New fictional image controls; references are used only after inference."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from scripts.participantkit.format_v1 import MISSING


def prepare(output, font_dir):
    if output.exists():
        raise ValueError('Fresh output required')
    output.mkdir(parents=True)
    records = []
    for index, mode in enumerate(['positive', 'positive', 'positive', 'positive',
                                  'staff_date', 'quoted', 'negated', 'duplicate']):
        font_name = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf'][index % 4]
        font_file = font_dir / font_name
        font = ImageFont.truetype(str(font_file), 28)
        image = Image.new('RGB', (1400, 1800), 'white')
        draw = ImageDraw.Draw(image)
        name = ['Крыловой Агаты Денисовны', 'Фролова Мирона Львовича',
                'Дёминой Анфисы Леонидовны', 'Дроздова Луки Станиславовича'][index % 4]
        group = ['КС-714/2029', 'МБ-625/2028', 'ЛТ-891/2030', 'ПР-472/2027'][index % 4]
        printed = []

        def line(text, x, y):
            draw.text((x, y), text, font=font, fill='black')
            box = draw.textbbox((x, y), text, font=font)
            printed.append({'text': text, 'bbox': list(box), 'page': 0})

        line('Декану факультета прикладных наук', 650, 120)
        line('От ' + name, 650, 250)
        line(('Студентки группы ' if index % 2 == 0 else 'Студента группы ') + group, 650, 300)
        if mode == 'duplicate':
            line('От Малининой Зои Алексеевны', 650, 350)
            line('19 марта 2029 года', 650, 400)
        elif mode == 'staff_date':
            line('Согласовано деканом', 650, 350)
            line('19 марта 2029 года', 650, 400)
        else:
            line('19 марта 2029 года', 650, 350)
        line('Заявление на академический отпуск', 440, 600)
        request = 'Прошу в связи с уходом за ребёнком оформить академический отпуск с 01.04.2029 г. по 01.10.2029 г.'
        if mode == 'quoted':
            request = 'Пример: ' + request
        if mode == 'negated':
            request = 'Прошу не оформить академический отпуск с 01.04.2029 г. по 01.10.2029 г.'
        words = request.split()
        current = ''; y = 690
        for word in words:
            candidate = (current + ' ' + word).strip()
            if draw.textlength(candidate, font=font) > 1110 and current:
                line(current, 145, y); y += 46; current = word
            else:
                current = candidate
        line(current, 145, y)
        line('Приложения: подтверждающие документы.', 145, y+100)
        expected = {'student_name': name, 'group': group, 'course': MISSING,
                    'application_date': '2029-03-19', 'leave_reason': 'уходом за ребёнком',
                    'leave_start': '2029-04-01', 'leave_end': '2029-10-01', 'signature_present': False}
        if mode == 'staff_date':
            expected['application_date'] = MISSING
        if mode in {'quoted', 'negated'}:
            for key in ['leave_reason', 'leave_start', 'leave_end']:
                expected[key] = MISSING
        if mode == 'duplicate':
            for key in ['student_name', 'group', 'application_date']:
                expected[key] = MISSING
        file = output / f'{index+1:02d}-{mode}.png'
        image.save(file)
        records.append({'image': file.name, 'image_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                        'font': font_name, 'font_sha256': hashlib.sha256(font_file.read_bytes()).hexdigest(),
                        'mode': mode, 'expected': expected, 'printed': printed})
    (output/'manifest.json').write_text(json.dumps({'source': 'Original fictional prose image controls',
        'license': 'AGPL-3.0 project generator; font binaries excluded', 'trained': False,
        'scope': 'Eight synthetic development images; four positive layouts and four semantic negatives',
        'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    sheet = Image.new('RGB', (1120, 720), '#dddddd')
    for index, row in enumerate(records):
        with Image.open(output/row['image']) as page:
            page.thumbnail((280, 360)); sheet.paste(page, ((index%4)*280, (index//4)*360))
    sheet.save(output/'contact-sheet.png')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output, args.font_dir)


if __name__ == '__main__':
    main()
