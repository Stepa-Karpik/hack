"""Original procedural OCR targets; no imported documents or control answers."""
import argparse
import hashlib
import json
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def printed_lines(seed, page):
    rng = random.Random(seed)
    # Procedural surnames are deliberately fictional, not a correction dictionary.
    syllables = ['бел', 'веш', 'жур', 'кел', 'лин', 'мир', 'нёш', 'пир', 'теш', 'фир', 'чел', 'шар']
    surname = ''.join(rng.choice(syllables) for _ in range(3)).capitalize() + rng.choice(['ев', 'ин', 'ов', 'ский'])
    given = rng.choice(['Арсений', 'Тимофей', 'Руслан', 'Глеб', 'Мирон', 'Ярослав'])
    patronymic = rng.choice(['Арсеньевич', 'Тимофеевич', 'Русланович', 'Глебович', 'Миронович', 'Ярославович'])
    name = f'{surname} {given} {patronymic}'
    if not page:
        return [rng.choice(['', 'ФИО студента: ', 'ФИО руководителя: ']) + name], name
    lines = ['УЧЕБНЫЙ ОБРАЗЕЦ', 'СПРАВКА ОБ ОБУЧЕНИИ', f'ФИО студента: {name}',
             f'Номер справки: КВ-{rng.randrange(10000, 99999)}',
             f'Дата выдачи: {rng.randrange(1, 29):02d}.{rng.randrange(1, 13):02d}.2028',
             f'Курс: {rng.randrange(1, 6)}',
             'Университет: Институт «Лаборатория ветра»',
             'Вымышленные сведения']
    return lines, name


def validate_partitions(partitions):
    names, seeds, pixels = set(), set(), set()
    for rows in partitions.values():
        for row in rows:
            for seen, value in [(names, row['fictional_name']), (seeds, row['seed']), (pixels, row['sha256'])]:
                if value in seen:
                    raise ValueError('Correlated name/seed/image crosses records; regenerate before training')
                seen.add(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('A fresh data directory is required')
    args.output.mkdir(parents=True)
    fonts = ['arial.ttf', 'times.ttf', 'calibri.ttf', 'verdana.ttf']
    partitions = {}
    for split, start, count in [('train', 202631000, 120), ('val', 202632000, 12), ('test', 202633000, 12)]:
        rows = []
        for i in range(count):
            seed = start + i
            page = i % 4 == (i // 4) % 4
            lines, name = printed_lines(seed, page)
            font_name = fonts[i % 4]
            font_file = args.font_dir / font_name
            size = [18, 22, 26, 30][(i // 4) % 4]
            font = ImageFont.truetype(str(font_file), size)
            image = Image.new('RGB', (1240, 1754) if page else (1040, 112), 'white')
            draw = ImageDraw.Draw(image)
            boxes = []
            for j, line in enumerate(lines):
                x, y = (80, 220 + j * (size + 20)) if page else (28, 32)
                bbox = list(draw.textbbox((x, y), line, font=font))
                if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > image.width or bbox[3] > image.height:
                    raise ValueError('Printed text clips the source image')
                draw.text((x, y), line, font=font, fill=(20, 20, 20))
                boxes.append(bbox)
            file = args.output / f'{split}-{i:03d}.png'
            image.save(file)
            rows.append({'image': file.name, 'sha256': sha(file), 'seed': seed,
                         'fictional_name': name, 'expected_lines': lines, 'target_text': '\n'.join(lines),
                         'printed_boxes': boxes, 'kind': 'fullpage_rehearsal' if page else 'literal_crop',
                         'font': font_name, 'font_sha256': sha(font_file), 'font_size': size})
        partitions[split] = rows
    validate_partitions(partitions)
    for split, rows in partitions.items():
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    manifest = {'source': 'Original procedural fictional text rendered locally; no organizer/real document imports',
                'license': 'Project-generated text/images; fonts excluded from redistribution',
                'seed_ranges': {'train': [202631000, 202631119], 'val': [202632000, 202632011], 'test': [202633000, 202633011]},
                'counts': {k: len(v) for k, v in partitions.items()},
                'scope': 'Disjoint full names/seeds/images; shared renderer/fonts/layouts, not independent real documents',
                'training_mix': '90 line crops and 30 complete eight-line pages',
                'generator_sha256': sha(Path(__file__)),
                'partition_sha256': {k: sha(args.output / f'{k}.jsonl') for k in partitions}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
