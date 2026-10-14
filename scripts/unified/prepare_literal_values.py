"""Original three-schema OCR pages; no imported answers or document pixels."""
import argparse
import itertools
import json
import random
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from scripts.participantkit.format_v1 import LABELS, MONTHS
from scripts.unified.contract import KEYS, MARKS
from scripts.unified.prepare_literal_training import sha, validate_partitions
from scripts.unified.text_binding import TITLES, DATES


def fictional_name(rng):
    syllables = ['бел', 'зор', 'лют', 'мер', 'нив', 'рут', 'тал', 'фен', 'хор', 'цел', 'чев', 'шар']
    surname = ''.join(rng.choice(syllables) for _ in range(4)).capitalize() + rng.choice(['ский', 'ов', 'ин'])
    return surname + ' ' + rng.choice(['Игнат', 'Родион', 'Арсений', 'Тимофей']) + ' ' + rng.choice(['Игнатьевич', 'Родионович', 'Арсеньевич', 'Тимофеевич'])


def date_text(day, month, style):
    return [f'{day:02d}.{month:02d}.2032', f'2032-{month:02d}-{day:02d}',
            f'{day:02d}/{month:02d}/2032', f'{day} {list(MONTHS)[month-1]} 2032 года'][style]


def content(seed, kind, date_style, blank_mode):
    rng = random.Random(seed)
    student, supervisor = fictional_name(rng), fictional_name(rng)
    values = dict(student_name=student, supervisor_name=supervisor,
                  university='Институт «' + rng.choice(['Северная мозаика', 'Лазурная орбита', 'Тихая долина']) + '»',
                  program=rng.choice(['Материаловедение', 'Прикладная механика', 'Городская экология']),
                  study_form=rng.choice(['очная', 'заочная', 'очно-заочная']),
                  document_number=f'УК-{rng.randrange(1000, 99999)}', group=f'ФМ-{rng.randrange(100, 999)}',
                  course=str(rng.randrange(1, 5)),
                  leave_reason=rng.choice(['семейные обстоятельства', 'продолжительное лечение', 'участие в экспедиции']),
                  organization='ООО «' + rng.choice(['Кедровый маяк', 'Серебряный контур', 'Зимний парус']) + '»',
                  grade=rng.choice(['отлично', 'хорошо', 'зачтено']))
    for key in sorted(DATES):
        values[key] = date_text(rng.randrange(1, 25), rng.randrange(1, 13), date_style)
    # Date values are OCR targets, not a claim of valid business chronology.
    blank_keys = [set(), {'student_name', 'supervisor_name'}, DATES,
                  {'group', 'course', 'document_number', 'organization', 'leave_reason'}][blank_mode]
    fields = {key: '' if key in blank_keys else values[key] for key in KEYS[kind] if key not in MARKS}
    lines = [TITLES[kind]] + [LABELS[key] + ': ' + value for key, value in fields.items()]
    lines += ['Контакт для связи: ', 'Все сведения вымышлены.']
    return lines, student, supervisor, fields


def render(lines, font, layout, size):
    image = Image.new('RGB', (1536, 2048), 'white')
    draw = ImageDraw.Draw(image)
    boxes = []
    for i, line in enumerate(lines):
        x = [90, 175, 110, 230][layout] + (35 * (i % 2) if layout == 3 else 0)
        y = [110, 320, 180, 140][layout] + i * [size + 16, size + 30, size + 12, size + 26][layout]
        if layout == 2 and i >= 5:
            y += 160
        box = list(draw.textbbox((x, y), line, font=font))
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Printed glyphs clip image')
        if boxes and boxes[-1][3] >= box[1]:
            raise ValueError('Printed lines overlap')
        draw.text((x, y), line, font=font, fill=(18, 18, 18))
        boxes.append(box)
    if layout == 1:
        draw.rectangle((130, 270, 1420, boxes[-1][3] + 40), outline=(100, 100, 100), width=2)
    return image, boxes


def design(split):
    # Every schema crosses every date style and blank pattern. Font and layout
    # use separate shuffled balanced schedules, never derived from blank/date.
    factors = list(itertools.product(TITLES, range(4), range(4)))
    if split == 'train':
        factors *= 4
    rng = random.Random({'train': 202661, 'val': 202662, 'test': 202663}[split])
    rng.shuffle(factors)
    schedules = []
    for levels in [4, 4, 2]:
        schedule = list(range(levels)) * (len(factors) // levels)
        rng.shuffle(schedule)
        schedules.append(schedule)
    return [(*factors[i], *(schedule[i] for schedule in schedules)) for i in range(len(factors))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    parser.add_argument('--prior-data', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh dataset directory required')
    fonts = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf']
    partitions = {}
    args.output.mkdir(parents=True)
    for split, start in [('train', 202661000), ('val', 202662000), ('test', 202663000)]:
        rows = []
        for i, (kind, date_style, blank_mode, font_index, layout, size_index) in enumerate(design(split)):
            size = [24, 28][size_index]
            lines, student, supervisor, fields = content(start + i, kind, date_style, blank_mode)
            font_file = args.font_dir / fonts[font_index]
            image, boxes = render(lines, ImageFont.truetype(str(font_file), size), layout, size)
            path = args.output / f'{split}-{i:03d}.png'
            image.save(path)
            rows.append(dict(image=path.name, sha256=sha(path), seed=start+i,
                             fictional_name=student, supervisor_name=supervisor, expected_lines=lines,
                             target_text='\n'.join(lines), printed_boxes=boxes, printed_fields=fields,
                             font=font_file.name, font_sha256=sha(font_file), font_size=size,
                             layout=layout, date_style=date_style, blank_mode=blank_mode,
                             document_type=kind, kind='fullpage_schema_values'))
        partitions[split] = rows
    validate_partitions(partitions)
    prior = []
    for directory in args.prior_data:
        for split in partitions:
            prior += [json.loads(line) for line in (directory / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
    names = [r[key] for rows in partitions.values() for r in rows for key in ['fictional_name', 'supervisor_name']]
    old_names = {r[key] for r in prior for key in ['fictional_name', 'supervisor_name'] if key in r}
    if len(names) != len(set(names)) or set(names) & old_names:
        raise ValueError('New name collision')
    for key in ['seed', 'sha256']:
        if {r[key] for r in prior} & {r[key] for rows in partitions.values() for r in rows}:
            raise ValueError('Previous literal data overlap')
    for split, rows in partitions.items():
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)+'\n', encoding='utf-8')
    manifest = dict(counts={k: len(v) for k,v in partitions.items()}, generator_sha256=sha(Path(__file__)),
                    partition_sha256={k: sha(args.output/f'{k}.jsonl') for k in partitions},
                    prior_literal_rows_checked=len(prior),
                    source='Original procedural fictional text and pixels; schema labels only, no kit/real answers',
                    license='Project AGPL-3.0 text/images; local Windows fonts not redistributed',
                    scope='Shared renderer/font/procedural pools; not independent real accuracy or app/graphic qualification',
                    design='Full schema x date-style x blank-mode crossing in each split; independently shuffled balanced font/layout/size schedules. Not every higher-order combination is covered.',
                    dates='OCR targets only; random date fields do not guarantee chronological business validity',
                    graphic_targets=False,
                    cross_counts={k: dict(Counter(f"{r['document_type']}|{r['date_style']}|{r['blank_mode']}" for r in v)) for k,v in partitions.items()})
    (args.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    sheet = Image.new('RGB', (1536, 1536), '#dddddd')
    for i,row in enumerate(partitions['val'][:12]):
        with Image.open(args.output/row['image']) as image:
            sheet.paste(image.resize((384,512)), ((i%4)*384,(i//4)*512))
    sheet.save(args.output/'qa-contact-sheet.png')
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
