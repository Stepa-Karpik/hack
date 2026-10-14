"""Experimental literal binding of one network's OCR text; no other model.

No synthetic geometry or OCR probabilities are assigned. Graphic marks remain
unknown: their captions never demonstrate presence or absence.
"""
import re

from scripts.unified.contract import KEYS, MARKS
from scripts.participantkit.format_v1 import LABELS, MISSING, iso

TITLES = {
    'study_certificate': 'СПРАВКА ОБ ОБУЧЕНИИ',
    'academic_leave_application': 'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК',
    'internship_certificate': 'СПРАВКА О ПРАКТИКЕ',
}
DATES = {'study_start', 'study_end', 'issue_date', 'application_date',
         'leave_start', 'leave_end', 'internship_start', 'internship_end'}


def bind(text, *, truncated=False):
    """Return literal text values/offsets, or abstain on ambiguous titles.

    Only same-line explicit labels are currently supported. Newlines are never
    borrowed to populate an empty field. Arbitrary prose needs separate guards.
    """
    if not isinstance(text, str):
        raise TypeError('OCR text required')
    if truncated:
        return {'document_type': None, 'fields': {}, 'audit': {},
                'reason': 'truncated_ocr', 'complete_document_check': False}
    lines = [(m.group().strip(), m.start(), m.end())
             for m in re.finditer(r'[^\r\n]+', text)]
    found = {kind for kind, title in TITLES.items()
             if any(line.casefold() == title.casefold() for line, _, _ in lines)}
    if len(found) != 1:
        return {'document_type': None, 'fields': {}, 'audit': {},
                'reason': 'missing_or_conflicting_title', 'complete_document_check': False}
    kind = found.pop()
    fields = {key: None for key in KEYS[kind]}
    audit = {}
    for key in KEYS[kind]:
        if key in MARKS:
            audit[key] = {'status': 'unknown', 'source': 'graphic_not_checked'}
            continue
        label = re.escape(LABELS[key]).replace(r'\ ', r'\s+')
        candidates = []
        for line, start, end in lines:
            match = re.fullmatch(label + r'\s*:\s*(.*)', line, re.I)
            if not match:
                continue
            literal = match[1].strip()
            value = literal
            if not literal or re.fullmatch(r'[\s_.—–-]+', literal):
                value = None
            elif key in DATES:
                value = iso(literal)
                value = None if value == MISSING else value
            elif key == 'course' and not re.fullmatch(r'\d+', literal):
                value = None
            candidates.append({'literal': literal, 'value': value,
                               'ocr_text_span': [start, end]})
        values = {c['value'] for c in candidates}
        conflict = len(values) > 1
        value = None if conflict or not candidates else candidates[0]['value']
        fields[key] = value
        audit[key] = {'status': 'conflict' if conflict else 'uncertain' if value is not None else 'not_found',
                      'source': 'single_network_ocr_explicit_label', 'semantic_confidence': None,
                      'source_confidence': None, 'bbox': None, 'coordinate_space': None,
                      'candidates': candidates}
    return {'document_type': kind, 'fields': fields, 'audit': audit,
            'reason': 'explicit_labels_only', 'complete_document_check': False}
