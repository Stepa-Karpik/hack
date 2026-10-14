"""Missing-only literal study-prose binding from the same native OCR output."""
import copy
import re
from scripts.participantkit.format_v1 import iso, MISSING

NAME = r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?'
DATE = r'\d{1,2}[./]\d{1,2}[./]\d{4}'


def recover(text, binding, *, truncated=False):
    result = copy.deepcopy(binding)
    if truncated or binding.get('document_type') != 'study_certificate':
        return result
    titles = list(re.finditer(r'(?im)^\s*СПРАВКА ОБ ОБУЧЕНИИ\s*$', text))
    if len(titles) != 1:
        return result
    body_start = titles[0].end()
    body = text[body_start:]
    # A direct student declaration must occur at the start of the body.
    declarations = list(re.finditer(r'(?m)^\s*(?P<name>'+NAME+r'\s+'+NAME+r'\s+'+NAME+r')\s+является\s+студент(?:ом|кой)\s+(?P<course>[1-6]|первого|второго|третьего|четв[её]ртого|пятого|шестого)\s+курса\b', body))
    if len(declarations) != 1 or len(re.findall(r'является\s+студент(?:ом|кой)\b', body, re.I)) != 1 or body[:declarations[0].start()].strip():
        return result

    def add(key, candidates):
        if key not in result['fields']:
            return
        if result['fields'].get(key) is not None or result['audit'].get(key, {}).get('status') == 'conflict':
            return
        if result['audit'].get(key, {}).get('candidates'):
            return
        values = {value for value, span in candidates if value is not None and value.strip()}
        if len(values) != 1 or len(candidates) == 0 or any(value is None for value, span in candidates):
            return
        value = values.pop()
        result['fields'][key] = value
        result['audit'][key] = dict(status='uncertain', source='single_network_ocr_literal_study_prose',
                                   semantic_confidence=None, source_confidence=None, bbox=None,
                                   coordinate_space=None, geometry_verified=False,
                                   candidates=[dict(value=v, ocr_text_span=span) for v,span in candidates])

    declaration = declarations[0]
    offset = body_start
    name = re.sub(r'\s+', ' ', declaration['name'])
    add('student_name', [(name, [offset+declaration.start('name'), offset+declaration.end('name')])])
    programs = list(re.finditer(r'Обучается\s+по\s+образовательной\s+программе\s+(.{1,500}?)\.\s+Форма\s+обучения\s*:', body, re.I | re.S))
    if len(programs) == 1 and len(re.findall(r'Обучается\s+по\s+образовательной\s+программе\b', body, re.I)) == 1:
        m=programs[0]
        add('program', [(re.sub(r'\s+', ' ', m[1]).strip(), [offset+m.start(1),offset+m.end(1)])])
    forms = list(re.finditer(r'Форма\s+обучения\s*:\s*(очно-заочная|заочная|очная)(?=[\s.]|$)', body, re.I))
    if len(forms) == len(re.findall(r'Форма\s+обучения\s*:', body, re.I)):
        add('study_form', [(m[1], [offset+m.start(1), offset+m.end(1)]) for m in forms])
    periods = list(re.finditer(r'Период\s+обучения\s*:\s*('+DATE+r')\s*[-–—]\s*('+DATE+r')', body, re.I))
    if len(periods) == 1 and len(re.findall(r'Период\s+обучения\s*:', body, re.I)) == 1:
        m = periods[0]
        start, end = iso(m[1]), iso(m[2])
        if start != MISSING and end != MISSING and start <= end:
            add('study_start', [(start, [offset+m.start(1),offset+m.end(1)])])
            add('study_end', [(end, [offset+m.start(2),offset+m.end(2)])])
    # Only explicitly quoted university names, with repeated identical names allowed.
    universities = []
    for m in re.finditer(r'«([^«»]{1,240})»', text):
        value = re.sub(r'\s+', ' ', m[1]).strip()
        if re.search(r'\bуниверситет\b', value, re.I):
            universities.append((value, [m.start(1),m.end(1)]))
    add('university', universities)
    # Header date and registration number must be one unique line before the title.
    headers = list(re.finditer(r'(?m)^\s*('+DATE+r')\s+№\s*([^\r\n]+?)\s*$', text[:titles[0].start()]))
    if len(headers) == 1:
        m=headers[0];value=iso(m[1])
        if value != MISSING:
            add('issue_date', [(value,[m.start(1),m.end(1)])])
            add('document_number', [(m[2].strip(),[m.start(2),m.end(2)])])
    return result
