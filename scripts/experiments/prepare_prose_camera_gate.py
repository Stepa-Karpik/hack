"""Recover the previous camera cohorts without passing answers to inference.

Font original pixels are read from the frozen six-image archive, not regenerated
with new fonts. Source metadata may route a manual type but never fills fields.
"""
import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--font-inputs', type=Path, required=True)
    p.add_argument('--official-inputs', type=Path, required=True)
    p.add_argument('--old-camera', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh dataset directory required')
    from dekanat.io import read_pages
    from dekanat.photo_augment import conditions
    old = json.loads(args.old_camera.read_text(encoding='utf-8'))['rows']
    expected_hashes = {r['id']: r['input_sha256'] for r in old}
    if len(expected_hashes) != 76:
        raise ValueError('Exactly 76 unique frozen camera identities required')
    source_records = json.loads(args.official_inputs.read_text(encoding='utf-8'))['records']
    paths = {r['id']: (r['input'], r['sha256']) for r in source_records}
    sources = sorted({r['id'].split('/')[0] for r in old})
    if len(sources) != 4:
        raise ValueError('Four source PDFs required')
    args.output.mkdir(parents=True)
    rows = []

    def save(identifier, image, routing, group, previous_hash=None):
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        pixels = buffer.getvalue()
        sha = hashlib.sha256(pixels).hexdigest()
        if previous_hash is not None and sha != previous_hash:
            raise ValueError('Transformed pixels differ from frozen camera input: ' + identifier)
        file = args.output/f'{len(rows):04d}.png'
        file.write_bytes(pixels)
        rows.append({'id': identifier, 'input': str(file.resolve()), 'sha256': sha,
                     'document_type': routing})
        return {'id': identifier, 'sha256': sha, 'group': group,
                'routing': routing, 'previous_pixel_sha_equal': sha == previous_hash if previous_hash else None}

    provenance = []
    for source_id in sources:
        path, source_hash = paths[source_id]
        file = Path(path)
        blob = file.read_bytes()
        if hashlib.sha256(blob).hexdigest() != source_hash:
            raise ValueError('Source PDF SHA mismatch')
        pages = read_pages(blob, file.name)
        if len(pages) != 1:
            raise ValueError('Frozen camera source must have one page')
        for name, transform in conditions().items():
            identity = source_id + '/' + name
            provenance.append(save(identity, transform(pages[0]), 'auto', 'external_camera', expected_hashes[identity]))
    with zipfile.ZipFile(args.font_inputs) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt frozen font archive')
        images = sorted(n for n in archive.namelist() if n.endswith('.png'))
        if len(images) != 6:
            raise ValueError('Six frozen font source images required')
        for filename in images:
            match = re.fullmatch(r'\d+_(study|leave|practice)\.png', filename)
            if not match:
                raise ValueError('Unrecognized frozen manual-type source')
            image = Image.open(io.BytesIO(archive.read(filename))).convert('RGB')
            transforms = list(conditions().items()) + [
                (f'quarter_{deg}', lambda image, deg=deg: image.rotate(deg, expand=True))
                for deg in (90, 180, 270)]
            for name, transform in transforms:
                provenance.append(save(filename + '/' + name, transform(image), match[1], 'fonts_camera'))
    if len(rows) != 208:
        raise ValueError('Frozen cohort requires 76 + 132 cases')
    (args.output/'inputs.json').write_text(json.dumps({'inputs': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    proof = {'scope': 'Same viewed development cohorts. Four source PDFs under 19 transforms, auto routing; '
             'six frozen font originals under 19 transforms and 3 rotations, original manual routing. '
             'Only pixels and declared routing reach inference; no expected field values.',
             'documents': 208, 'external_camera': 76, 'fonts_camera': 132,
             'all_external_camera_pixels_equal_previous': True,
             'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (args.font_inputs, args.official_inputs, args.old_camera)},
             'augmentation_sha256': hashlib.sha256(Path('dekanat/photo_augment.py').read_bytes()).hexdigest(),
             'rows': provenance}
    (args.output/'provenance.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared 208 cases; all 76 camera PNG hashes match previous inputs')


if __name__ == '__main__':
    main()
