"""Field highlight regions from the same model's Spotting output (line quads).

A field gets a region only when its value (or the literal it was read from) is
found in one line or in up to three consecutive lines; the region is the union
of those line boxes, in 0..1 image coordinates. Nothing is inferred from
line order alone; graphic marks get no text region.
"""
import re

from scripts.participantkit.format_v1 import MONTHS
from scripts.unified.spotting_name_crops import regions as spotting_regions

MONTH_NAMES = list(MONTHS)


def _norm(text):
    text = str(text).casefold().replace('ё', 'е').replace('«', '"').replace('»', '"')
    return re.sub(r'\s+', ' ', text).strip()


def _variants(value, literals=()):
    out = {_norm(v) for v in literals if isinstance(v, str) and len(v.strip()) >= 2}
    if isinstance(value, str) and value.strip() and value != 'не найдено':
        out.add(_norm(value))
        m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value)
        if m:
            y, mo, d = m.groups()
            out |= {f'{d}.{mo}.{y}', f'{int(d)}.{mo}.{y}', f'{d}/{mo}/{y}', f'{y}-{mo}-{d}',
                    f'{int(d)} {MONTH_NAMES[int(mo) - 1]} {y}', f'«{d}» {MONTH_NAMES[int(mo) - 1]} {y}'}
    return {v for v in out if v}


def field_regions(spotting_text, fields, audit=None):
    lines = spotting_regions(spotting_text)
    texts = [_norm(line['text']) for line in lines]
    result = []
    for key, value in fields.items():
        if isinstance(value, bool) or value in (None, 'не найдено'):
            continue
        literals = [c.get('literal') or c.get('value') for c in ((audit or {}).get(key) or {}).get('candidates') or []]
        variants = sorted(_variants(value, literals), key=len, reverse=True)
        hit = None
        for size in (1, 2, 3):
            for start in range(len(lines) - size + 1):
                joined = ' '.join(texts[start:start + size])
                if any(v in joined for v in variants):
                    hit = lines[start:start + size]
                    break
            if hit:
                break
        if not hit:
            continue
        box = [min(h['box_0_1000'][0] for h in hit), min(h['box_0_1000'][1] for h in hit),
               max(h['box_0_1000'][2] for h in hit), max(h['box_0_1000'][3] for h in hit)]
        result.append({'field': key, 'page': 0, 'bbox': [round(v / 1000, 4) for v in box],
                       'source': 'same_model_spotting_line', 'geometry_verified': False})
    return result
