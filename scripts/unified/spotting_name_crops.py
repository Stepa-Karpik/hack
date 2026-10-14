"""Bounded image crops from native spotting quadrilaterals and visible colon.

No expected names, references or inferred image boxes from text line numbers.
This prepares diagnostic crops only, never changes an extracted field.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from scripts.participantkit.format_v1 import LABELS


LOC = r'<\|LOC_(\d{1,4})\|>'
BLOCK = re.compile(r'([^<>]+?)' + LOC*8)


def regions(text):
    result = []
    for match in BLOCK.finditer(text):
        points = [int(v) for v in match.groups()[1:]]
        if any(not 0 <= v <= 1000 for v in points):
            continue
        xs, ys = points[::2], points[1::2]
        box = [min(xs), min(ys), max(xs), max(ys)]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        result.append({'text': match[1].strip(), 'quad': points, 'box_0_1000': box})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--spotting', type=Path, required=True)
    p.add_argument('--images-root', type=Path, required=True)
    p.add_argument('--field', choices=['student_name', 'supervisor_name'], required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh crop directory required')
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    from scripts.participantkit.value_quote_recovery import colon_cuts
    report = json.loads(args.spotting.read_text(encoding='utf-8'))
    if not report['complete'] or report['task'] != 'spotting':
        raise ValueError('Complete native spotting required')
    args.output.mkdir(parents=True)
    rows = []
    pattern = re.compile(r'^' + re.escape(LABELS[args.field]) + r'\s*:', re.I)
    for r in report['rows']:
        paths = list(args.images_root.rglob(r['file'])) if Path(r['file']).name == r['file'] else []
        if len(paths) != 1 or not paths[0].resolve().is_relative_to(args.images_root.resolve()):
            raise ValueError('Unique source image inside root required')
        path = paths[0]
        if hashlib.sha256(path.read_bytes()).hexdigest() != r['input_sha256']:
            raise ValueError('Source image SHA mismatch')
        options = [b for b in regions(r['raw']) if pattern.match(b['text'])]
        row = {'source_image': path.name, 'input_sha256': r['input_sha256'], 'field': args.field,
               'native_spotting_regions': options, 'crops': [], 'reason': 'ambiguous_or_missing_label'}
        if len(options) == 1 and not r['token_budget_reached']:
            with Image.open(path) as im:
                image = ImageOps.exif_transpose(im).convert('RGB')
            x1, y1, x2, y2 = options[0]['box_0_1000']
            bounds = [max(0, math.floor(x1*image.width/1000)-6), max(0, math.floor(y1*image.height/1000)-6),
                      min(image.width, math.ceil(x2*image.width/1000)+6), min(image.height, math.ceil(y2*image.height/1000)+6)]
            row['source_pixel_line_bbox'] = bounds
            if 12 <= bounds[3]-bounds[1] <= 160 and 100 <= bounds[2]-bounds[0] <= 2000:
                gray = cv2.cvtColor(np.asarray(image.crop(bounds)), cv2.COLOR_RGB2GRAY)
                cuts = colon_cuts(gray)
                row['colon_candidates'] = cuts
                row['reason'] = 'ambiguous_or_missing_colon'
                if len(cuts) == 1 and gray.shape[1]-cuts[0] > 60:
                    value = Image.fromarray(gray[:, cuts[0]+1:])
                    row['source_pixel_value_bbox'] = [bounds[0]+cuts[0]+1, bounds[1], bounds[2], bounds[3]]
                    for scale in (1, 2):
                        crop = value if scale == 1 else value.resize((value.width*2, value.height*2), Image.Resampling.BICUBIC)
                        name = f'{len(rows):02d}-gray-{scale}x.png'
                        file = args.output/name
                        crop.save(file)
                        row['crops'].append({'image': name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'scale': scale})
                    row['reason'] = 'prepared_no_field_change'
            else:
                row['reason'] = 'line_crop_budget'
        rows.append(row)
    (args.output/'manifest.json').write_text(json.dumps({'scope': 'Native quadrilateral geometry + deterministic '
        'visible colon components, grayscale and bicubic2x value crops. No second recognizer/detector or expected names. '
        'Study only; no deployed field changes or independent evidence.', 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('prepared', sum(bool(r['crops']) for r in rows), 'of', len(rows), 'source labels')


if __name__ == '__main__':
    main()
