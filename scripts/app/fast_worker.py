"""CPU reader for machines without a GPU: the project's fast engine (EasyOCR + YOLO + field rules).

Same stdin/stdout protocol as scripts.unified.native_worker: one JSON request per line
{"task": "ocr", "input": path, "output": path, "document_type": "auto" | official type},
one JSON reply per line. Models are loaded once. Field geometry comes with the result,
so field highlighting needs no second pass. Runs in the first-generation environment
(requirements.txt: easyocr, ultralytics, scikit-learn).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KINDS = {'study_certificate': 'study', 'academic_leave_application': 'leave', 'internship_certificate': 'practice'}
OFFICIAL = {v: k for k, v in KINDS.items()}
# official field -> first-generation field holding its evidence
RAW_KEYS = {'signature_present': 'signature', 'seal_present': 'stamp', 'study_start': 'study_period', 'study_end': 'study_period',
            'internship_start': 'practice_period', 'internship_end': 'practice_period', 'leave_reason': 'reason',
            'leave_start': 'start_date', 'leave_end': 'end_date', 'supervisor_name': 'supervisor'}


QUOTED = ('university', 'organization')


def normalize_quotes(value):
    """The CRNN reads guillemets around names as '<', 'к', '>' or 'э' («Парус» -> кПарус>).

    Only a quote glyph glued to a capitalised word is replaced; letters are never invented.
    """
    import re
    if not isinstance(value, str):
        return value
    fixed = re.sub(r'(^|\s)[<«кk"~](?=[А-ЯЁ])', lambda m: m.group(1) + '«', value)
    if fixed != value and '»' not in fixed:  # both quotes misread: the closing one became >, э, х or ж
        fixed = re.sub(r'[>»эхж"]?\s*$', '', fixed) + '»'
    elif '«' in fixed and '»' not in fixed:  # only the closing quote is missing or became >
        fixed = re.sub(r'[>"]?\s*$', '', fixed) + '»'
    return fixed


LATIN_TO_CYRILLIC = str.maketrans('aceopxyACEHKMOPTXB', 'асеорхуАСЕНКМОРТХВ')


def normalize_script(value, key):
    """Latin look-alikes inside Russian text («c уходом» -> «с уходом»), a zero in a letter prefix (0Б-1003 -> ОБ-1003)."""
    import re
    if not isinstance(value, str):
        return value
    if key in QUOTED + ('supervisor_name', 'student_name') and len(re.findall('[А-Яа-яЁёA-Za-z]', value)) < 3:
        return 'не найдено'  # a number or a stray mark is not a name
    if not re.search('[А-Яа-яЁё]', value):
        return value
    words = []
    for word in value.split(' '):
        if re.fullmatch(r'[aceopxyACEHKMOPTXB]+', word) and len(word) <= 2 or (
                re.search('[А-Яа-яЁё]', word) and re.search('[A-Za-z]', word)):
            word = word.translate(LATIN_TO_CYRILLIC)
        words.append(word)
    value = ' '.join(words)
    if key == 'supervisor_name':  # «Руководитель практики от организации: …» -> the label tail is not a name
        value = re.sub(r'^(от\s+(организации|предприятия|кафедры|вуза)?\s*:?\s*)', '', value, flags=re.I).strip()
        if len(re.findall(r'[А-ЯЁ][а-яё]+', value)) < 2:
            return 'не найдено'
    if key in QUOTED and len(re.findall('[А-Яа-яЁёA-Za-z]', value)) < 3:  # a number is not an institution name
        return 'не найдено'
    if key == 'group':
        value = re.sub(r'(?<=[\d-]) (?=\d)', '', value)
        # the digit part after the hyphen: «]», «|», «l», «I» are a misread «1» (ИВТ-2] -> ИВТ-21)
        value = re.sub(r'(?<=-)[\dIl|\]]+$', lambda m: re.sub(r'[Il|\]]', '1', m.group(0)) if re.search(r'\d', m.group(0)) else m.group(0), value)
    if key == 'document_number':
        value = re.sub(r'^([0-9А-ЯЁ]+)(?=-)', lambda m: m.group(1).replace('0', 'О') if re.search('[А-ЯЁ]', m.group(1)) else m.group(1), value)
    return value


def live_overlay(analysis, regions, pages):
    """Field boxes mapped back from the rectified page onto the camera frame, the sheet outline and quality warnings."""
    import numpy as np
    meta = (analysis.get('preprocessing') or [{}])[0]
    matrix = np.asarray(meta.get('rectified_to_input') or np.eye(3))
    in_w, in_h = meta.get('input_size') or (pages[0].size if pages else (1, 1))
    page_w, page_h = pages[0].size if pages else (1, 1)

    def to_frame(x, y):
        u, v, t = matrix @ np.array([x * page_w, y * page_h, 1.0])
        return [float(u / t / in_w), float(v / t / in_h)]
    live = []
    for r in regions:
        x0, y0, x1, y1 = r['bbox']
        live.append({'field': r['field'], 'kind': r.get('kind'),
                     'quad': [to_frame(x0, y0), to_frame(x1, y0), to_frame(x1, y1), to_frame(x0, y1)]})
    perspective = meta.get('perspective') or {}
    sheet = [[float(x / in_w), float(y / in_h)] for x, y in perspective.get('corners_input', [])] if perspective.get('applied') else None
    share = None
    if sheet and len(sheet) >= 3:  # shoelace area of the sheet outline, as a share of the frame
        share = round(abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(sheet, sheet[1:] + sheet[:1]))) / 2, 3)
    return {'regions': live, 'sheet': sheet, 'sheet_share': share, 'warnings': (meta.get('quality') or {}).get('warnings') or []}


PERIODS = {'academic_leave_application': ('leave_start', 'leave_end', r'отпуск'),
           'internship_certificate': ('internship_start', 'internship_end', r'практик'),
           'study_certificate': ('study_start', 'study_end', r'обучени|обучает')}
REASONS = r'по\s+(семейным\s+обстоятельствам|медицинским\s+показаниям|состоянию\s+здоровья)'


def period_fallback(fields, text, kind):
    """A period written in prose and read out of order by OCR («отпуск 15.10.2026 по с 14.10.2027»): the first two
    dates after the anchor word, in increasing order. Only fills fields that are still missing."""
    import re
    from scripts.participantkit.format_v1 import DATE, MISSING, iso
    changed = False
    flat = re.sub(r'\s+', ' ', text or '')
    if kind in PERIODS:
        start, end, anchor = PERIODS[kind]
        if fields.get(start) == MISSING and fields.get(end) == MISSING:
            for m in re.finditer(anchor, flat, re.I):
                dates = [iso(d) for d in re.findall(DATE, flat[m.end():m.end() + 160], re.I)]
                dates = [d for d in dates if d != MISSING]
                if len(dates) >= 2 and dates[0] < dates[1]:
                    fields[start], fields[end] = dates[0], dates[1]
                    changed = True
                    break
    if kind == 'academic_leave_application' and fields.get('leave_reason') == MISSING:
        m = re.search(REASONS, flat, re.I)
        if m:
            fields['leave_reason'] = 'по ' + re.sub(r'\s+', ' ', m.group(1)).lower()
            changed = True
    return changed


UNREADABLE = ('Текст на снимке читается плохо, поэтому часть сведений могла не найтись. Переснимите документ ближе, '
              'при ровном свете и без бликов, или загрузите скан.')


def readability(analysis):
    """Recognizer confidence over the text lines: a photo of a screen or a blurred frame reads ~0.3, a usable photo 0.8+."""
    lines = [l for l in analysis['ocr']['lines'] if len(l['text']) >= 4 and isinstance(l.get('confidence'), (int, float))]
    warnings = list(dict.fromkeys(w for page in analysis.get('preprocessing') or [] for w in (page.get('quality') or {}).get('warnings') or []))
    if not lines:
        return {'mean_confidence': None, 'low_share': None, 'readable': False, 'warnings': warnings + [UNREADABLE]}
    mean = sum(l['confidence'] for l in lines) / len(lines)
    low = sum(1 for l in lines if l['confidence'] < 0.4) / len(lines)
    readable = mean >= 0.5 and low <= 0.4  # chosen on 9 photos/scans: unreadable 0.31/0.74, usable 0.68-0.88 / <=0.10
    return {'mean_confidence': round(mean, 3), 'low_share': round(low, 3), 'readable': readable,
            'warnings': warnings + ([] if readable else [UNREADABLE])}


def missing_places(fields, analysis, size):
    """Where a missing mark is expected: the printed caption «(подпись)» / «М.П.» on the page."""
    import re
    width, height = size
    # the small italic caption under a signature line is often misread («(тодтutcъ)», «{нодuсъ)»): a short bracketed word
    places = {'signature_present': r'\(\s*подп\w{0,4}|подпись\s+(студента|руководителя|сотрудника)|^\s*[({\[]\s*\S{4,9}\s*[)}\]]\s*$',
              'seal_present': r'\bм\s*\.?\s*п\s*\.?\b|место\s+печати'}
    regions = []
    for key, pattern in places.items():
        if fields.get(key) is False:
            hits = [l for l in analysis['ocr']['lines'] if re.search(pattern, l['text'], re.I) and len(l['text']) < 60]
            if hits:
                b = max(hits, key=lambda l: l['bbox'][1])['bbox']  # the lowest caption: the signature block
                pad = (b[3] - b[1]) * 1.2
                regions.append({'field': key, 'page': 0, 'kind': 'missing', 'source': 'printed_caption',
                                'bbox': [max(0, (b[0] - pad) / width), max(0, (b[1] - 2 * pad) / height),
                                         min(1, (b[2] + pad) / width), min(1, (b[3] + pad) / height)]})
    return regions


def read(path, output, requested, quick=False, custom_types=None):
    from dekanat.pipeline import analyze
    from scripts.app import custom_types as custom_mod
    from scripts.participantkit.service import prepare_result
    path, output = Path(path), Path(output)
    data = path.read_bytes()
    started = time.perf_counter()
    kind = KINDS.get(requested, 'auto')
    # quarter-turn recovery re-reads the page up to 3 times; rotations are outside the case (README v1.0)
    orientation = os.environ.get('DEKANAT_ORIENTATION', '0') == '1'
    side = os.environ.get('DEKANAT_DETECT_SIDE', '1536')
    if quick:  # live camera frames: a smaller detector canvas, ~2 s instead of ~6 s
        os.environ['DEKANAT_DETECT_SIDE'] = '1024'
    try:
        pages, analysis = analyze(data, path.name, document_type=kind, gpu=False, orientation=orientation)
    finally:
        os.environ['DEKANAT_DETECT_SIDE'] = side
    # a bold printed heading (a company name in the letterhead) is not a handwritten signature or a stamp
    page0 = [l for l in analysis['ocr']['lines'] if l.get('page', 0) == 0]
    for mark in ('signature', 'stamp'):
        f = (analysis.get('fields') or {}).get(mark) or {}
        box = (f.get('evidence') or {}).get('bbox')
        if f.get('value') is True and box and custom_mod.over_text(box, page0):
            f['value'] = False
    detected = analysis.get('type')
    # a type from the constructor: chosen by the user, or its title phrase is on the page
    custom_types = custom_types or []
    custom = next((c for c in custom_types if c['key'] == requested), None) or (
        custom_mod.match(custom_types, analysis['ocr']['lines'], strict=bool(detected)) if requested == 'auto' else None)
    if custom:
        detected = None
    official_type = custom['key'] if custom else OFFICIAL.get(detected)
    row = {'engine': 'cpu-fast', 'file': path.name, 'input_sha256': hashlib.sha256(data).hexdigest(),
           'detected_type': official_type, 'document_type': official_type}
    lines = sorted(analysis['ocr']['lines'], key=lambda l: (l.get('page', 0), round(l['bbox'][1] / 18), l['bbox'][0]))
    text, current = [], None
    for line in lines:  # rows of boxes -> reading-order text
        key = (line.get('page', 0), round(line['bbox'][1] / 18))
        if current is not None and key == current:
            text[-1] += ' ' + line['text']
        else:
            text.append(line['text'])
        current = key
    row['ocr_text'] = '\n'.join(text)
    size = pages[0].size if pages else (1, 1)
    if custom:
        from dekanat.visual import classify
        from dekanat.schema import ROOT as MODELS
        visual = [m for m, on in (('signature', custom.get('signature')), ('stamp', custom.get('seal'))) if on]
        marks = classify(pages, visual, MODELS / 'models' / 'visual.pt', False) if visual and pages else {}
        row.update(custom_mod.extract(custom, [l for l in analysis['ocr']['lines'] if l.get('page', 0) == 0], marks, size))
        row['regions'] += missing_places(row['fields'], analysis, size)
    elif detected:
        official = OFFICIAL[detected]
        result, audit = prepare_result(pages, analysis, official, [], gpu=False)
        for key, value in result['fields'].items():
            if isinstance(value, str) and value != 'не найдено':
                value = normalize_script(value, key)
                result['fields'][key] = normalize_quotes(value) if key in QUOTED else value
        if period_fallback(result['fields'], row['ocr_text'], official):
            from scripts.participantkit.format_v1 import validate
            from scripts.participantkit.service import load_config
            result['validation'] = validate(result['fields'], official, load_config())
        width, height = pages[0].size if pages else (1, 1)
        statuses, confidence, regions = {}, {}, []
        for key, value in result['fields'].items():
            raw = analysis['fields'].get(RAW_KEYS.get(key, key)) or {}
            binding = audit['bindings'].get(key) or {}
            parts = [part for part in binding.get('parts') or [] if isinstance(part.get('confidence'), (int, float))]
            conf = min(part['confidence'] for part in parts) if parts else raw.get('confidence')
            statuses[key] = 'conflict' if binding.get('status') == 'conflict' or raw.get('conflict') else (
                'found' if value not in (None, False, 'не найдено') else 'not_found')
            confidence[key] = round(float(conf), 4) if isinstance(conf, (int, float)) else None
            if value in (None, False, 'не найдено'):
                continue
            boxes = [part['bbox'] for part in binding.get('parts') or [] if part.get('bbox')]
            if not boxes and (raw.get('evidence') or {}).get('bbox'):
                boxes = [raw['evidence']['bbox']]
            if boxes:
                x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
                x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
                regions.append({'field': key, 'page': 0, 'bbox': [max(0, x0 / width), max(0, y0 / height), min(1, x1 / width), min(1, y1 / height)],
                                'source': 'cpu_fast_evidence'})
        regions += missing_places(result['fields'], analysis, size)
        row.update({'fields': result['fields'], 'validation': result['validation'], 'statuses': statuses,
                    'confidence': confidence, 'regions': regions})
    row['quality'] = readability(analysis)
    if (custom or detected) and pages:  # rectified page = the geometry of the regions
        image = pages[0].convert('RGB').copy()
        image.thumbnail((1700, 2200))
        image.save(output.with_name('preview.png'))
    if quick:
        row['live'] = live_overlay(analysis, row.get('regions') or [], pages)
        row['live']['warnings'] = row['quality']['warnings']
        row['live']['readable'] = row['quality']['readable']
    row['seconds'] = round(time.perf_counter() - started, 3)
    output.write_text(json.dumps({'engine': 'cpu-fast', 'rows': [row]}, ensure_ascii=False, default=lambda v: v.tolist()),
                      encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--threads', type=int, default=int(os.environ.get('DEKANAT_THREADS', '6')))
    args = p.parse_args()
    import torch
    torch.set_num_threads(args.threads)
    os.environ.setdefault('DEKANAT_DETECT_SIDE', '1536')  # chosen on the organizer kit: 1024 loses dates, 2000 is slower
    os.environ.setdefault('DEKANAT_OCR_BATCH', '32')
    os.environ.setdefault('DEKANAT_CACHE', str(ROOT / 'models/cache'))
    from dekanat.pipeline import analyze  # noqa: F401  (load code before reporting ready)
    from dekanat.ocr import get_reader
    reader = get_reader(False, True)
    # channels-last convolutions: the text detector is ~20% faster on CPU, same results
    reader.detector = reader.detector.to(memory_format=torch.channels_last)
    sample = ROOT / 'web-app/assets/samples/study.png'
    if sample.exists():  # warm-up: every model of the engine is loaded before the first real document
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            read(sample, Path(folder) / 'warm.json', 'auto')
    print(json.dumps({'ready': True, 'engine': 'cpu-fast'}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get('task', 'ocr') != 'ocr':
                raise ValueError('cpu-fast engine supports the ocr task only')
            read(request['input'], request['output'], request.get('document_type', 'auto'), bool(request.get('quick')),
                 request.get('custom_types'))
            reply = {'ok': True}
        except Exception as error:  # reported per document, the worker keeps running
            reply = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)[:300]}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
