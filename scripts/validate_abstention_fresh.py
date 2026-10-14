"""Locked field-specific hypotheses on new fictional fonts/values; no deployment."""
import hashlib
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image
from evaluate_field_abstention import evaluate_rule, region_quality

ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES = [('student_name', 'minimum_sharpness', 100), ('document_number', 'confidence', .65)]
NAMES = ['Дмитриева Анна Викторовна', 'Фёдорова Елена Борисовна', 'Тихонов Артём Юрьевич',
         'Романова Ольга Денисовна', 'Беляев Семён Фёдорович', 'Громова Мария Олеговна']


def build_inputs(target):
    sys.path.insert(0, str(ROOT))
    from dekanat import synthetic
    original_values, original_font = synthetic.values, synthetic.font_path
    documents = []
    try:
        for index, (font, kind) in enumerate((font, kind) for font in ['times.ttf', 'georgia.ttf'] for kind in ['study', 'leave', 'practice']):
            path = Path('C:/Windows/Fonts')/font
            if not path.is_file():
                raise FileNotFoundError(path)
            def values(rng, index=index, kind=kind):
                result = original_values(rng)
                result.update(student_name=NAMES[index], document_number={'study':'ИС', 'leave':'АП', 'practice':'ПР'}[kind]+'-'+str(8100+index))
                return result
            synthetic.values = values
            synthetic.font_path = lambda path=path: str(path)
            seed, template = 2026101900+index, 81+index
            image, truth = synthetic.document(seed, template=template, document_type=kind, missing_rate=0, force_marks=(True, kind!='leave'))
            name = f'{index}_{kind}'
            buffer = io.BytesIO(); image.save(buffer, format='PNG')
            documents.append((name, buffer.getvalue(), {'type':kind, 'fields':truth['fields'], 'seed':seed,
                             'template':template, 'font':font, 'font_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
    finally:
        synthetic.values, synthetic.font_path = original_values, original_font
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, pixels, metadata in documents:
            archive.writestr(name+'.png', pixels)
            archive.writestr(name+'.json', json.dumps(metadata, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=ROOT/'artifacts/field_abstention_fresh.json')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from dekanat.pipeline import analyze
    from dekanat.photo_augment import conditions
    from dekanat.extraction import normalize
    inputs = ROOT/'artifacts/field_abstention_fresh_inputs.zip'
    if not inputs.exists():
        build_inputs(inputs)
    rows = []
    with zipfile.ZipFile(inputs) as archive:
        assert archive.testzip() is None
        for metadata_name in sorted(n for n in archive.namelist() if n.endswith('.json')):
            truth = json.loads(archive.read(metadata_name))
            source = Image.open(io.BytesIO(archive.read(metadata_name.replace('.json', '.png')))).convert('RGB')
            transforms = list(conditions().items()) + [(f'quarter_{degrees}', lambda image, degrees=degrees: image.rotate(degrees, expand=True)) for degrees in [90, 180, 270]]
            for name, transform in transforms:
                buffer = io.BytesIO(); transform(source).save(buffer, format='PNG')
                pages, result = analyze(buffer.getvalue(), 'fresh.png', truth['type'], retry=True)
                for key, expected in truth['fields'].items():
                    if isinstance(expected, bool):
                        continue
                    field = result['fields'][key]
                    rows.append({'document':metadata_name, 'font':truth['font'], 'type':truth['type'], 'condition':name,
                                 'field':key, 'expected':expected, 'value':field['value'], 'status':field['status'],
                                 'confidence':field['confidence'], 'correct':field['value'] is not None and normalize(str(field['value']))==normalize(str(expected)),
                                 **region_quality(pages, field.get('evidence'))})
                print(metadata_name, name, flush=True)
    trials = [{'field':key, **evaluate_rule([r for r in rows if r['field']==key], metric, threshold)} for key, metric, threshold in HYPOTHESES]
    report = {'scope':'Six new fictional documents: Times New Roman/Georgia, novel student names and document numbers, seeds 2026101900..1905/templates81..86. 19 camera conditions + three quarter turns each, 132 cases/924 text fields. Same synthetic generator, not real camera accuracy; first evaluation with thresholds fixed from prior development, now viewed and not independent for future tuning.',
              'hypotheses_locked_before_inference':HYPOTHESES, 'trials':trials,
              'input_archive_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),
              'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')},
              'models':json.loads((ROOT/'artifacts/release_manifest.json').read_text())['model_hashes'],
              'total':len(rows), 'correct':sum(r['correct'] for r in rows),
              'correct_found':sum(r['correct'] and r['status']=='found' for r in rows),
              'confident_wrong':sum(not r['correct'] and r['status']=='found' for r in rows),
              'rows':rows, 'deployment':'None. Reject any hypothesis losing a correct found; passing synthetic checks alone does not prove target-photo safety.'}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['rows', 'runtime_sha256', 'models']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
