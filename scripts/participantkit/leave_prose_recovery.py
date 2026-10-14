"""Preserved guarded revision plus literal year-abbreviation tolerance."""
import math
import re

from dekanat.extraction import merge_rows
from dekanat.narrative import windows
from scripts.participantkit._leave_prose_guarded import recover as guarded
from scripts.participantkit.format_v1 import MISSING, iso


def recover(fields, bindings, analysis):
    result, evidence, changes, rejected = guarded(fields, bindings, analysis)
    if analysis.get('type') != 'leave':
        return result, evidence, changes, rejected
    lines = [r for r in analysis.get('ocr', {}).get('lines', [])
             if isinstance(r.get('bbox'), (list, tuple)) and len(r['bbox']) == 4
             and all(isinstance(v, (float, int)) and math.isfinite(v) for v in r['bbox'])
             and isinstance(r.get('confidence'), (float, int)) and .3 <= r['confidence'] <= 1]
    rows = merge_rows(lines)
    titles = [r for r in rows if re.fullmatch(r'Заявление\s+на\s+академический\s+отпуск', r['text'], re.I)]
    if len(titles) != 1:
        return result, evidence, changes, rejected
    title = titles[0]
    body = [r for r in rows if r['page'] == title['page'] and r['bbox'][1] > title['bbox'][3]]
    options = []
    date = r'\d{1,2}\.\d{1,2}\.\d{4}'
    for parts in windows(body, relaxed=True):
        text = ' '.join(r['text'] for r in parts)
        if not re.match(r'^\s*Прошу\b', text, re.I) or re.search(r'\bне\s+(?:оформлять|оформить|предоставлять|предоставить)\b', text, re.I):
            continue
        match = re.search(r'\bакадемический\s+отпуск\s+[сc]\s+(' + date + r')\s*(?:г[.:]?)?\s+по\s+(' + date + r')(?:\s|$|[.;])', text, re.I)
        if not match:
            continue
        start, end = iso(match[1]), iso(match[2])
        if MISSING not in (start, end) and start <= end:
            options.append((start, end, parts))
    if len({(s, e) for s, e, _ in options}) != 1:
        return result, evidence, changes, rejected
    start, end, parts = options[0]
    for key, value, raw_key in [('leave_start', start, 'start_date'), ('leave_end', end, 'end_date')]:
        raw = analysis.get('fields', {}).get(raw_key, {})
        if (result.get(key) != MISSING or fields.get(key) != MISSING or raw.get('status') != 'not_found'
                or raw.get('value') is not None or bindings.get(key, {}).get('status') == 'conflict'):
            continue
        result[key] = value
        evidence[key] = {'status': 'uncertain', 'value': value, 'semantic_confidence': None,
            'source': 'experimental_leave_year_abbreviation',
            'evidence': {'method': 'bounded_leave_prose', 'rule': 'literal_year_abbreviation_range',
                'text': ' '.join(r['text'] for r in parts), 'parts': parts, 'page': parts[0]['page'],
                'source_confidence': min(r['confidence'] for r in parts),
                'bbox': [min(r['bbox'][0] for r in parts), min(r['bbox'][1] for r in parts),
                         max(r['bbox'][2] for r in parts), max(r['bbox'][3] for r in parts)]}}
        changes.append({'field': key, 'value': value, 'status': 'uncertain'})
    return result, evidence, changes, rejected
