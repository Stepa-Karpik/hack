"""Original dense-page literal OCR training with new seeds and fictional names."""
import argparse
import json
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from scripts.unified.prepare_literal_training import sha, validate_partitions


def page_lines(seed, index):
    rng = random.Random(seed)
    syllables = ['брай', 'валь', 'гёр', 'даль', 'зель', 'йор', 'кля', 'лён', 'нэй', 'рёв', 'сель', 'таль', 'хель', 'щёл']
    surname = ''.join(rng.choice(syllables) for _ in range(3)).capitalize() + rng.choice(['ев', 'ин', 'ов', 'ский'])
    name = surname + ' ' + rng.choice(['Захар', 'Игнат', 'Родион', 'Филипп', 'Леон', 'Всеволод']) + ' ' + rng.choice(['Захарович', 'Игнатьевич', 'Родионович', 'Филиппович', 'Леонович', 'Всеволодович'])
    blank = index % 6 == 0
    number = f'ЛК-{rng.randrange(10000, 99999)}'
    date = f'{rng.randrange(1, 29):02d}.{rng.randrange(1, 13):02d}.2029'
    org = 'Институт «' + rng.choice(['Тихий меридиан', 'Лунная мастерская', 'Северный предел', 'Зеркальная долина']) + '»'
    lines = ['ВЫМЫШЛЕННЫЙ УЧЕБНЫЙ ОБРАЗЕЦ',
             ['СПРАВКА ОБ ОБУЧЕНИИ', 'СВЕДЕНИЯ О ПРАКТИКЕ', 'ЗАЯВЛЕНИЕ', 'РЕГИСТРАЦИОННАЯ КАРТОЧКА'][index % 4],
             'ФИО студента: ' + ('' if blank else name),
             'Университет: ' + org, 'Номер документа: ' + number,
             'Дата выдачи: ' + date, 'Курс: ' + ('' if blank else str(rng.randrange(1, 6))),
             'Период: 17.03.2029 — 24.08.2029',
             'Организация: ' + ('не указана' if blank else 'ООО «Равновесие света»'),
             'Сведения приведены в учебных целях.']
    if index % 3 == 0:
        lines += ['Заполнение необязательного поля: ', 'Пустое поле не содержит значения.']
    return lines, name, blank


def boxes_valid(boxes, width, height):
    return all(0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height for b in boxes) and all(a[3] <= b[1] for a, b in zip(boxes, boxes[1:]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve previous datasets; use a fresh directory')
    args.output.mkdir(parents=True)
    fonts = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf']
    splits = [('train', 202641000, 72), ('val', 202642000, 12), ('test', 202643000, 12)]
    partitions = {}
    for split, start, count in splits:
        rows = []
        for i in range(count):
            lines, name, blank = page_lines(start + i, i)
            size = [20, 24, 28][(i // 4) % 3]
            font_file = args.font_dir / fonts[i % 4]
            font = ImageFont.truetype(str(font_file), size)
            image = Image.new('RGB', (1536, 2048), 'white')
            draw = ImageDraw.Draw(image)
            boxes = []
            x, y = [90, 160, 240][(i // 12) % 3], [160, 350, 540][(i // 4) % 3]
            for j, line in enumerate(lines):
                position = (x, y + j * (size + [12, 20, 30][i % 3]))
                draw.text(position, line, font=font, fill=(18, 18, 18))
                boxes.append(list(draw.textbbox(position, line, font=font)))
            if not boxes_valid(boxes, *image.size):
                raise ValueError('Clipped or overlapping printed line')
            file = args.output / f'{split}-{i:03d}.png'
            image.save(file)
            rows.append({'image': file.name, 'sha256': sha(file), 'seed': start + i,
                         'fictional_name': name, 'expected_lines': lines, 'target_text': '\n'.join(lines),
                         'printed_boxes': boxes, 'font': font_file.name, 'font_sha256': sha(font_file),
                         'font_size': size, 'blank_fields': blank, 'kind': 'dense_fullpage'})
        partitions[split] = rows
    validate_partitions(partitions)
    for split, rows in partitions.items():
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    manifest = {'source': 'New procedural fictional full pages, no imported documents or control answers',
                'license': 'Original project-generated text/images AGPL-3.0; local fonts not redistributed',
                'counts': {k: len(v) for k, v in partitions.items()},
                'seed_ranges': {k: [s, s + n - 1] for k, s, n in splits},
                'training_mix': '72 full pages; four title styles, 10/12 lines, 12 blank-field pages',
                'scope': 'Disjoint full names/seeds/images; shared generator/fonts/text pools, not independent real documents',
                'generator_sha256': sha(Path(__file__)),
                'partition_sha256': {k: sha(args.output / f'{k}.jsonl') for k in partitions}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
