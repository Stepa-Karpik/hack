"""Guarded revision of the preserved leave-prose experiment, not deployed."""
import re

from dekanat.extraction import merge_rows
from scripts.experiments.leave_prose import recover as initial_recover


def recover(fields, bindings, analysis):
    result, evidence, changes = initial_recover(fields, bindings, analysis)
    rows = merge_rows(analysis.get('ocr', {}).get('lines', [])) if changes else []
    rejected = []
    for change in changes:
        key = change['field']
        parts = evidence[key]['evidence']['parts']
        reason = None
        if key == 'application_date':
            sender, _, date, _ = parts
            if any(r['page'] == sender['page'] and sender['bbox'][3] <= r['bbox'][1] < date['bbox'][3]
                   and re.match(r'\s*(?:Декан|Ректор|Согласовано|Утверждаю|Резолюция|Решение|Сотрудник|Руководитель)\b', r['text'], re.I)
                   for r in rows):
                reason = 'intervening_staff_context'
        elif key in {'leave_reason', 'leave_start', 'leave_end'}:
            text = ' '.join(r['text'] for r in parts)
            if not re.match(r'^\s*Прошу\b', text, re.I):
                reason = 'not_direct_applicant_request'
            elif re.search(r'\bне\s+(?:оформлять|оформить|предоставлять|предоставить)\b', text, re.I):
                reason = 'negated_leave_request'
        if reason:
            result[key] = fields[key]
            if key in bindings:
                evidence[key] = bindings[key]
            else:
                evidence.pop(key, None)
            rejected.append({'field': key, 'reason': reason})
    return result, evidence, [c for c in changes if c['field'] not in {r['field'] for r in rejected}], rejected
