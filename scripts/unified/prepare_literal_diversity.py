"""Original fullpage OCR diversity; never imports document answers or name controls."""
import argparse
import json
import random
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from scripts.unified.prepare_literal_training import sha, validate_partitions


def content(seed, blank, date_style):
    rng = random.Random(seed)
    surname = ''.join(rng.choice(['дра', 'плю', 'фро', 'цю', 'шве', 'жда', 'сню', 'тро', 'вру', 'чра', 'зню', 'шлю']) for _ in range(4)).capitalize() + rng.choice(['ан', 'ец', 'ун'])
    name = surname + ' ' + rng.choice(['Елисей', 'Савелий', 'Демьян', 'Платон']) + ' ' + rng.choice(['Елисеевич', 'Савельевич', 'Демьянович', 'Платонович'])
    day, month = rng.randrange(1, 24), rng.randrange(1, 10)
    dates = [(f'{day:02d}.{month:02d}.2031', f'{day + 4:02d}.{month + 2:02d}.2031'),
             (f'2031-{month:02d}-{day:02d}', f'2031-{month + 2:02d}-{day + 4:02d}'),
             (f'{day:02d}/{month:02d}/2031', f'{day + 4:02d}/{month + 2:02d}/2031'),
             (f'{day} марта 2031 года', f'{day + 4} июня 2031 года')][date_style]
    lines = ['ВЫМЫШЛЕННЫЕ УЧЕБНЫЕ СВЕДЕНИЯ', 'Карточка учебного обращения',
             'ФИО заявителя: ' + ('' if blank else name),
             'Группа: ' + ('' if blank else f'ДР-{rng.randrange(100, 999)}'),
             f'Номер обращения: СД-{rng.randrange(10000, 99999)}',
             'Дата начала: ' + dates[0], 'Дата окончания: ' + dates[1],
             'Место обучения: Академия «Облачный мост»',
             'Цель обращения: оформление учебного периода',
             'Контакт: ', 'Примечание: все сведения вымышлены.',
             'Пустое поле оставлено без значения.']
    return lines, name


def positions(layout, size):
    # Every line has a unique vertical position, including the two separated blocks.
    if layout == 0:
        return [(100, 120 + i * (size + 22)) for i in range(12)]
    if layout == 1:
        return [(180 if i < 2 else 260, 360 + i * (size + 12)) for i in range(12)]
    if layout == 2:
        return [(90 if i < 6 else 390, 140 + i * (size + 19) + (240 if i >= 6 else 0)) for i in range(12)]
    return [(120 + (i % 3) * 45, 190 + i * (size + 34)) for i in range(12)]


def render(lines, font, layout, size):
    image = Image.new('RGB', (1536, 2048), 'white')
    draw = ImageDraw.Draw(image)
    boxes = []
    for line, position in zip(lines, positions(layout, size)):
        box = list(draw.textbbox(position, line, font=font))
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Printed glyphs clip image')
        if boxes and boxes[-1][3] >= box[1]:
            raise ValueError('Printed lines overlap or order is ambiguous')
        draw.text(position, line, font=font, fill=(18, 18, 18))
        boxes.append(box)
    if layout == 1:
        draw.rectangle((140, 310, 1390, boxes[-1][3] + 40), outline=(100, 100, 100), width=2)
    return image, boxes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    parser.add_argument('--prior-data', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh dataset required')
    fonts = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf']
    partitions = {}
    args.output.mkdir(parents=True)
    for split, start, count in [('train', 202651000, 64), ('val', 202652000, 16), ('test', 202653000, 16)]:
        rows = []
        for i in range(count):
            font_index, layout = i % 4, (i // 4) % 4
            cycle = i // 16
            size = [24, 28][(font_index + layout + cycle) % 2]
            blank = (font_index + layout + cycle) % 4 == 0
            date_style = (font_index + layout + cycle) % 4
            lines, name = content(start + i, blank, date_style)
            font_file = args.font_dir / fonts[font_index]
            image, boxes = render(lines, ImageFont.truetype(str(font_file), size), layout, size)
            file = args.output / f'{split}-{i:03d}.png'
            image.save(file)
            rows.append(dict(image=file.name, sha256=sha(file), seed=start + i, fictional_name=name,
                             expected_lines=lines, target_text='\n'.join(lines), printed_boxes=boxes,
                             font=font_file.name, font_sha256=sha(font_file), font_size=size,
                             layout=layout, date_style=date_style, blank_fields=blank, kind='fullpage_diversity'))
        partitions[split] = rows
    prior = []
    for directory in args.prior_data:
        for split in ['train', 'val', 'test']:
            prior.extend(json.loads(line) for line in (directory / f'{split}.jsonl').read_text(encoding='utf-8').splitlines())
    validate_partitions(partitions)
    # Old datasets may repeat internally; only require the new rows to be disjoint from them.
    for key in ['fictional_name', 'seed', 'sha256']:
        if {r[key] for r in prior} & {r[key] for rows in partitions.values() for r in rows}:
            raise ValueError('New cohort overlaps previous literal data')
    for split, rows in partitions.items():
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    manifest = dict(source='New procedural fictional fullpages; no imported kit/real documents or answers',
                    license='Original project text/images AGPL-3.0; local Windows fonts not redistributed',
                    scope='Shared renderer, text/name pools and fonts; not independent real accuracy',
                    counts={k: len(v) for k, v in partitions.items()}, generator_sha256=sha(Path(__file__)),
                    partition_sha256={k: sha(args.output / f'{k}.jsonl') for k in partitions},
                    prior_literal_rows_checked=len(prior),
                    design='All 16 font/layout pairs per split, two glyph sizes, four date styles; train four cycles, controls one cycle each. Blank/name fields rotate across fonts and layouts; date style and blanks still coupled by construction.',
                    margins='All glyph boxes bounded, strictly ordered and non-overlapping; one-page only',
                    blank_counts={k: sum(r['blank_fields'] for r in v) for k, v in partitions.items()},
                    layout_counts={k: dict(Counter(r['layout'] for r in v)) for k, v in partitions.items()})
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    sheet = Image.new('RGB', (4 * 384, 4 * 512), '#dddddd')
    for i, row in enumerate(partitions['val']):
        with Image.open(args.output / row['image']) as image:
            sheet.paste(image.resize((384, 512)), ((i % 4) * 384, (i // 4) * 512))
    sheet.save(args.output / 'val-contact-sheet.png')
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
