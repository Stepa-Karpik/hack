"""Isolated native-text candidate; never imported by the application.

Clone only extraction's function globals to qualify canonicalisation BEFORE
candidate merging. No monkeypatch or replacement of existing conflict fields.
"""
import re
from types import FunctionType
from dekanat import extraction
from dekanat.slots import NAME, fill_missing_slots
from dekanat.field_validation import validate_fields, parse_numeric_date

ROLE = r'от\s+организации\s*\(предприятия\)'


def canonical(key, value):
    # Literal full name following an exact role, optional comma-delimited job.
    # Initials/extra names/unknown suffixes are not guessed or truncated.
    if key == 'supervisor':
        match = re.fullmatch(ROLE + r'\s+(' + NAME + r')(?:,\s*(?:руководитель отдела|директор))?', value.strip())
        if match:
            value = match[1]
    return extraction.canonical_value(key, value)


def shifted_signature_date(lines, fields, kind):
    field = fields.get('application_date')
    if kind != 'leave' or not field or field.get('value') is not None or field.get('status') != 'not_found':
        return []
    rows = extraction.merge_rows(lines)
    proposals = []
    for row in rows:
        if not parse_numeric_date(row['text']):
            continue
        height = row['bbox'][3] - row['bbox'][1]
        signatures = [p for p in rows if p['page'] == row['page'] and
                      re.fullmatch(r'\(подпись\)', p['text'], re.IGNORECASE) and
                      0 <= row['bbox'][1] - p['bbox'][3] < 2*height and
                      -height <= row['bbox'][0] - p['bbox'][2] < 2*height]
        requests = [p for p in rows if p['page'] == row['page'] and
                    p['bbox'][3] < row['bbox'][1] and re.search(r'Прошу предоставить', p['text'], re.IGNORECASE)]
        if len(signatures) != 1 or not requests:
            continue
        request = max(requests, key=lambda p: p['bbox'][1])
        staff = [p for p in rows if p['page'] == row['page'] and
                 request['bbox'][3] < p['bbox'][1] < row['bbox'][1] and
                 re.match(r'(?:Академическ[а-я]* руководител[а-я]*|Декан|Ректор)\b', p['text'], re.IGNORECASE)]
        if not staff:
            proposals.append((row, signatures[0], request))
    if len(proposals) != 1:
        return []
    row, signature, request = proposals[0]
    confidence = min(p['confidence'] for p in (row, signature, request))
    # Diagnostic source certainty only, not calibrated semantic probability.
    fields['application_date'] = {'value': row['text'], 'status': 'found' if confidence >= .55 else 'uncertain',
        'confidence': confidence, 'evidence': {'method': 'native_shifted_signature_date_experiment',
            'text': '\n'.join(p['text'] for p in (request, signature, row)), 'page': row['page'],
            'confidence': confidence, 'bbox': row['bbox'], 'parts': [request, signature, row]}}
    return [{'field': 'application_date', 'rule': 'unique_shifted_signature_date'}]


def extract_candidate(lines, kind, model):
    globals_copy = dict(extraction.extract.__globals__, canonical_value=canonical)
    isolated = FunctionType(extraction.extract.__code__, globals_copy, 'native_extract_candidate',
                            extraction.extract.__defaults__, extraction.extract.__closure__)
    isolated.__kwdefaults__ = extraction.extract.__kwdefaults__
    fields = isolated(lines, kind, model) if kind else {}
    changes = []
    supervisor = fields.get('supervisor')
    if supervisor and isinstance(supervisor.get('value'), str) and supervisor['status'] == 'found':
        if re.fullmatch(ROLE + r'[_\s.]*', supervisor['value'].strip(), re.IGNORECASE):
            supervisor['status'] = 'uncertain'
            supervisor.setdefault('validation', []).append({'rule': 'native_role_placeholder',
                'reason': 'Role and empty fill line do not identify a supervisor; raw value/evidence retained.'})
            changes.append({'field': 'supervisor', 'rule': 'placeholder_review'})
    changes.extend(fill_missing_slots(lines, fields, kind)['changes'])
    changes.extend(shifted_signature_date(lines, fields, kind))
    validate_fields(fields)
    return fields, changes
