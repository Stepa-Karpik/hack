"""Fictional full-page controls for spotting/name-region geometry.

Printed targets are evaluation-only; no fitting and no participant names used.
Windows font binaries are recorded by hash and are not redistributed.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--fonts', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh controls directory required')
    args.output.mkdir(parents=True)
    names = ['Тарновская Алёна Витальевна', 'Бережников Роман Юрьевич',
             'Дорофеева Инна Леонидовна', 'Князев Тимур Евгеньевич']
    fonts = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf']
    rows = []
    for i in range(8):
        path = args.fonts/fonts[i % 4]
        font = ImageFont.truetype(str(path), 28)
        image = Image.new('RGB', (1400, 900), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((80, 70), 'Учебный образец / вымышленные данные', font=font, fill='black')
        draw.text((80, 140), 'Справка о прохождении практики', font=font, fill='black')
        draw.text((80, 230), 'ФИО студента: Демидов Семён Алексеевич', font=font, fill='black')
        label = 'ФИО руководителя практики:'
        mode = 'positive' if i < 4 else ['blank', 'duplicate', 'neighbor_note', 'two_columns'][i-4]
        draw.text((80, 350), label + (' '+names[i % 4] if i < 4 else ''), font=font, fill='black')
        if mode == 'duplicate':
            draw.text((80, 450), label+' '+names[1], font=font, fill='black')
        elif mode == 'neighbor_note':
            draw.text((80, 430), 'Примечание: '+names[2]+' — контакт учебного отдела', font=font, fill='black')
        elif mode == 'two_columns':
            draw.text((780, 350), 'Контакт: '+names[3], font=font, fill='black')
        draw.text((80, 570), 'Оценка: отлично', font=font, fill='black')
        draw.text((80, 680), 'Подпись руководителя: __________________', font=font, fill='black')
        file = args.output/f'{i:02d}-{mode}.png'; image.save(file)
        rows.append({'id': file.stem, 'file': file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
            'font_file': path.name, 'font_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'layout': mode, 'printed_target': names[i % 4] if i < 4 else None,
            'expected_action': 'literal_crop_only' if i < 4 else 'no_field_fill',
            'scope': 'New fictional geometry development control, not independent real accuracy'})
    (args.output/'evaluation.json').write_text(json.dumps({'rows': rows, 'training': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared eight full-page controls; answers evaluation-only')


if __name__ == '__main__':
    main()
