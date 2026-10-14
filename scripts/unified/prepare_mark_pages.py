"""Original fictional pages with signatures and seals at known boxes (patch-level marks).

Layouts follow real Russian certificates: a signature block («Должность ____ И.О.
Фамилия», «(подпись)» captions), signatures drawn over the line, seals
overlapping text near «М.П.». Signature ink comes from the Ultralytics signature
dataset crops (AGPL-3.0, source split preserved: train crops -> train/val pages,
val crops -> test pages) or procedural scribbles; seals are procedural. Hard
negatives: empty signature lines with captions, «М.П.» without a seal, round
logos and stamps-like headers in other colours are included. No organizer or
user document pixels are read.
"""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from scripts.unified.prepare_natural_pages import FAMILIES, FONTS, Pools, compose, render, sentences, clean_name

INKS = [(20, 30, 120), (25, 25, 30), (40, 50, 150), (60, 40, 140), (15, 60, 140)]
SEAL_INKS = [(40, 70, 170), (70, 50, 160), (30, 90, 170), (110, 60, 150)]
POSITIONS = ['Декан факультета', 'Начальник учебного управления', 'Руководитель практики', 'Проректор по учебной работе',
             'Студент', 'Директор', 'Секретарь учебной части', 'Заведующий кафедрой']


def ink_from_crop(path, label_path):
    """Extract signature strokes as an alpha mask from a photographed crop."""
    import numpy as np
    cls, x, y, w, h = map(float, Path(label_path).read_text().split()[:5])
    with Image.open(path) as im:
        W, H = im.size
        box = (max(0, int((x - w / 2) * W)), max(0, int((y - h / 2) * H)), min(W, int((x + w / 2) * W)), min(H, int((y + h / 2) * H)))
        gray = im.convert('L').crop(box)
    arr = np.asarray(gray).astype('float32')
    background = np.asarray(gray.filter(ImageFilter.MedianFilter(31))).astype('float32')
    alpha = np.clip((background - arr - 18) / 55, 0, 1)
    mask = Image.fromarray((alpha * 255).astype('uint8'))
    bbox = mask.point(lambda v: 255 if v > 60 else 0).getbbox()
    return mask.crop(bbox) if bbox else None


def scribble(rng, width, height):
    """Procedural signature: a few smooth looping strokes."""
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    points, x = [], rng.uniform(0.02, 0.1) * width
    for _ in range(rng.randrange(7, 16)):
        x += rng.uniform(0.04, 0.12) * width
        points.append((min(x, width * 0.97), rng.uniform(0.15, 0.85) * height))
    stroke = max(2, int(height * rng.uniform(0.035, 0.07)))
    curve = []
    for i in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        cx, cy = (x0 + x1) / 2 + rng.uniform(-0.08, 0.08) * width, rng.uniform(0, 1) * height
        for t in [k / 12 for k in range(13)]:
            curve.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1))
    draw.line(curve, fill=255, width=stroke, joint='curve')
    if rng.random() < .6:  # underline flourish
        y = rng.uniform(0.6, 0.9) * height
        draw.line([(rng.uniform(0, .3) * width, y), (rng.uniform(.6, 1) * width, y - rng.uniform(-.1, .1) * height)], fill=255, width=stroke)
    return mask.filter(ImageFilter.GaussianBlur(0.6))


def seal(rng, diameter, family):
    """Procedural round or rectangular stamp as an alpha mask."""
    size = diameter
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    font_file = FONTS + FAMILIES[family][0]
    if rng.random() < .82:
        r = size / 2 - 3
        w = max(2, size // 60)
        d.ellipse([3, 3, size - 3, size - 3], outline=255, width=w)
        inner = r * rng.uniform(.62, .72)
        if rng.random() < .8:
            d.ellipse([size / 2 - inner, size / 2 - inner, size / 2 + inner, size / 2 + inner], outline=255, width=max(1, w - 1))
        text = rng.choice(['УЧЕБНОЕ УПРАВЛЕНИЕ', 'ДЛЯ ДОКУМЕНТОВ', 'ОТДЕЛ КАДРОВ', 'ДЕКАНАТ', 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ'])
        text = (text + ' * ' + rng.choice(['ИНН 7701234567', 'ОГРН 1027700000000', 'г. ' + rng.choice(['Казань', 'Пермь', 'Томск'])]) + ' * ')
        font = ImageFont.truetype(font_file, max(9, int(size * .075)))
        ring = (r + inner) / 2
        for i, ch in enumerate(text):
            angle = -math.pi / 2 + 2 * math.pi * i / len(text)
            glyph = Image.new('L', (int(size * .12), int(size * .12)), 0)
            ImageDraw.Draw(glyph).text((glyph.width / 2, glyph.height / 2), ch, font=font, fill=255, anchor='mm')
            glyph = glyph.rotate(-math.degrees(angle) - 90, resample=Image.BICUBIC)
            mask.paste(255, (int(size / 2 + ring * math.cos(angle) - glyph.width / 2), int(size / 2 + ring * math.sin(angle) - glyph.height / 2)), glyph)
        center = ImageFont.truetype(font_file, max(9, int(size * .09)))
        for k, line in enumerate(rng.choice([['ДЛЯ', 'ДОКУМЕНТОВ'], ['МАКЕТ'], ['ПЕЧАТЬ', '№ 2'], ['*']])):
            d.text((size / 2, size / 2 + (k - .5) * size * .12), line, font=center, fill=255, anchor='mm')
    else:
        h = int(size * rng.uniform(.4, .55))
        mask = Image.new('L', (size, h), 0)
        d = ImageDraw.Draw(mask)
        d.rectangle([2, 2, size - 3, h - 3], outline=255, width=max(2, size // 70))
        font = ImageFont.truetype(font_file, max(9, int(size * .07)))
        for k, line in enumerate(['ПОЛУЧЕНО', f'«{rng.randrange(1, 28)}» {rng.choice(["мая", "июня", "октября"])} 20{rng.randrange(20, 31)} г.', 'Вх. № ' + str(rng.randrange(10, 999))]):
            d.text((size / 2, h * (k + 1) / 4), line, font=font, fill=255, anchor='mm')
    if rng.random() < .5:  # uneven ink
        import numpy as np
        noise = Image.fromarray((np.random.default_rng(rng.randrange(1 << 30)).random((mask.height, mask.width)) * 255).astype('uint8')).filter(ImageFilter.GaussianBlur(3))
        mask = Image.composite(mask, Image.new('L', mask.size, 0), noise.point(lambda v: 255 if v > 90 else 120))
    return mask.rotate(rng.uniform(-25, 25), resample=Image.BICUBIC, expand=True)


def paste_ink(image, mask, xy, color, opacity):
    layer = Image.new('RGB', mask.size, color)
    alpha = mask.point(lambda v: int(v * opacity))
    image.paste(layer, xy, alpha)
    bbox = alpha.point(lambda v: 255 if v > 40 else 0).getbbox()
    return [xy[0] + bbox[0], xy[1] + bbox[1], xy[0] + bbox[2], xy[1] + bbox[3]] if bbox else None


def build_page(rng, pools, family, crops):
    blocks = compose(pools, rng)
    blocks = [b for b in blocks if b[0] != 'sign' and b[1] != 'М.П.']
    image, lines, boxes, size, owners = render(blocks, family, rng)
    W, H = image.size
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONTS + FAMILIES[family][0], max(14, size))
    small = ImageFont.truetype(FONTS + FAMILIES[family][0], max(11, int(size * .72)))
    ink_text = (30, 30, 30)
    y = (max(b[3] for b in boxes) if boxes else int(H * .3)) + int(size * rng.uniform(1.5, 3))
    if y > H * .8:
        y = int(H * .55)
        draw.rectangle([0, y - size, W, H], fill=image.getpixel((5, 5)))
    margin = int(W * rng.uniform(.08, .12))
    position = rng.choice(POSITIONS)
    draw.text((margin, y), position, font=font, fill=ink_text)
    y += int(size * 1.9)
    line_x0 = margin + rng.randrange(0, int(W * .05))
    line_w = int(W * rng.uniform(.18, .28))
    line_y = y + int(size * 1.4)
    style = rng.random()
    if style < .5:
        draw.line([(line_x0, line_y), (line_x0 + line_w, line_y)], fill=ink_text, width=max(1, size // 18))
    else:
        draw.text((line_x0, line_y - size), '_' * max(8, int(line_w / (size * .5))), font=font, fill=ink_text)
    name = pools.person()
    short = name.split()
    initials = f'{short[1][0]}.{short[2][0]}. {short[0]}' if len(short) == 3 and len(short[1]) > 2 else name
    name_x = line_x0 + line_w + int(W * .05)
    draw.text((name_x, line_y - size * 1.1), initials, font=font, fill=ink_text)
    if rng.random() < .75:
        draw.text((line_x0 + line_w * .3, line_y + size * .4), '(подпись)', font=small, fill=ink_text)
        draw.text((name_x, line_y + size * .4), '(расшифровка подписи)', font=small, fill=ink_text)
    labels = {'signature': [], 'seal': []}
    has_signature = rng.random() < .62
    if has_signature:
        sw = int(line_w * rng.uniform(.6, 1.15))
        sh = int(sw * rng.uniform(.28, .55))
        mask = None
        if crops and rng.random() < .55:
            mask = rng.choice(crops)
            mask = mask.resize((sw, max(8, int(sw * mask.height / max(1, mask.width)))), Image.LANCZOS)
        else:
            mask = scribble(rng, sw, sh)
        mask = mask.rotate(rng.uniform(-8, 8), resample=Image.BICUBIC, expand=True)
        x = int(line_x0 + rng.uniform(-.05, .3) * line_w)
        y0 = int(line_y - mask.height * rng.uniform(.45, .85))
        box = paste_ink(image, mask, (x, y0), rng.choice(INKS), rng.uniform(.75, 1))
        if box:
            labels['signature'].append(box)
    seal_xy = (int(margin + rng.uniform(-.02, .2) * W), int(line_y + size * rng.uniform(1.2, 2.8)))
    has_seal = rng.random() < .5
    if rng.random() < .55:
        draw.text((seal_xy[0] + int(W * .02), seal_xy[1] + int(size * .5)), 'М.П.', font=font, fill=ink_text)
    if has_seal:
        diameter = int(W * rng.uniform(.11, .18))
        mask = seal(rng, diameter, family)
        jitter = (seal_xy[0] + rng.randrange(-diameter // 3, diameter // 3), seal_xy[1] - rng.randrange(0, diameter // 2))
        box = paste_ink(image, mask, jitter, rng.choice(SEAL_INKS), rng.uniform(.55, .95))
        if box:
            labels['seal'].append(box)
    if rng.random() < .25:  # hard negative: coloured round logo in the header
        d = int(W * rng.uniform(.06, .09))
        logo = Image.new('L', (d, d), 0)
        ImageDraw.Draw(logo).ellipse([2, 2, d - 2, d - 2], fill=255)
        ImageDraw.Draw(logo).ellipse([d * .25, d * .25, d * .75, d * .75], fill=0)
        paste_ink(image, logo, (int(W * rng.uniform(.06, .1)), int(H * .03)), rng.choice([(180, 40, 40), (30, 120, 60), (200, 140, 20)]), 1)
    return image, labels


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sources', type=Path, required=True, help='ocr-v5/sources (names, prose)')
    p.add_argument('--signatures', type=Path, required=True, help='data/detection/source')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--train', type=int, default=360)
    p.add_argument('--val', type=int, default=60)
    p.add_argument('--test', type=int, default=60)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    args.output.mkdir(parents=True)
    names = json.loads((args.sources / 'wikidata_names.json').read_text(encoding='utf-8'))
    surnames = sorted({n for n in map(clean_name, names['family']) if n})
    wiki = json.loads((args.sources / 'ruwiki_rows.json').read_text(encoding='utf-8'))['articles']
    articles = [s for s in (sentences(a['text']) for a in wiki) if len(s) >= 4]
    crops = {}
    for split in ('train', 'val'):
        crops[split] = []
        for image in sorted((args.signatures / 'images' / split).glob('*.jpg')):
            mask = ink_from_crop(image, args.signatures / 'labels' / split / (image.stem + '.txt'))
            if mask is not None and mask.width > 20 and mask.height > 8:
                crops[split].append(mask)
    rng_split = random.Random(7)
    train_crops = crops['train'][:]
    rng_split.shuffle(train_crops)
    cut = int(len(train_crops) * .85)
    pools_by_split = {'train': train_crops[:cut], 'val': train_crops[cut:], 'test': crops['val']}
    families = sorted(FAMILIES)
    manifest = {'scope': __doc__.strip(), 'splits': {}, 'signature_crops': {k: len(v) for k, v in pools_by_split.items()}}
    for split, count, seed in (('train', args.train, 808000), ('val', args.val, 809000), ('test', args.test, 810000)):
        rows = []
        for i in range(count):
            rng = random.Random(seed + i)
            pools = Pools(surnames, articles, rng)
            family = rng.choice(families)
            image, labels = build_page(rng, pools, family, pools_by_split[split])
            if rng.random() < .3:
                image = image.filter(ImageFilter.GaussianBlur(rng.uniform(.3, .8)))
            name = f'{split}-{i:03d}.png'
            image.save(args.output / name)
            W, H = image.size
            rows.append({'image': name, 'sha256': hashlib.sha256((args.output / name).read_bytes()).hexdigest(), 'family': family,
                         'size': [W, H], 'signature': [[round(b[0] / W, 4), round(b[1] / H, 4), round(b[2] / W, 4), round(b[3] / H, 4)] for b in labels['signature']],
                         'seal': [[round(b[0] / W, 4), round(b[1] / H, 4), round(b[2] / W, 4), round(b[3] / H, 4)] for b in labels['seal']]})
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
        manifest['splits'][split] = {'count': len(rows), 'signature': sum(bool(r['signature']) for r in rows), 'seal': sum(bool(r['seal']) for r in rows)}
        print(split, manifest['splits'][split], flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
