"""Missing-only leave prose experiment; not connected to the deployed service.

Uses literal OCR rows only. No names, reference answers, IDs or university
dictionaries. Grammatical case is retained; names are never declined here.
"""
import copy
import math
import re
from collections import defaultdict

from dekanat.extraction import merge_rows
from dekanat.narrative import NAME, windows
from scripts.participantkit.format_v1 import MISSING, iso

DATE = r'\d{1,2}\.\d{1,2}\.\d{4}'


def recover(fields, bindings, analysis):
    result, evidence = copy.deepcopy(fields), copy.deepcopy(bindings)
    if analysis.get('type') != 'leave':
        return result, evidence, []
    lines = []
    for row in analysis.get('ocr', {}).get('lines', []):
        box, score = row.get('bbox'), row.get('confidence')
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
                or box[2] <= box[0] or box[3] <= box[1]
                or not isinstance(score, (int, float)) or not .3 <= score <= 1
                or not isinstance(row.get('page'), int) or row['page'] < 0):
            continue
        lines.append(row)
    rows = merge_rows(lines)
    titles = [r for r in rows if re.fullmatch(r'Заявление\s+на\s+академический\s+отпуск', r['text'], re.I)]
    if len(titles) != 1:
        return result, evidence, []
    title = titles[0]
    proposals = defaultdict(list)

    def emit(key, value, parts, rule):
        if key not in fields or not value or '_' in value:
            return
        proposals[key].append({'value': value, 'status': 'uncertain',
            'source': 'experimental_leave_prose', 'semantic_confidence': None,
            'evidence': {'method': 'bounded_leave_prose', 'rule': rule,
                'text': '\n'.join(r['text'] for r in parts), 'page': parts[0]['page'],
                'bbox': [min(r['bbox'][0] for r in parts), min(r['bbox'][1] for r in parts),
                         max(r['bbox'][2] for r in parts), max(r['bbox'][3] for r in parts)],
                'parts': parts, 'source_confidence': min(r['confidence'] for r in parts)}})

    # An explicitly named sender is not the rector named in the addressee.
    senders = [r for r in rows if r['page'] == title['page'] and r['bbox'][3] < title['bbox'][1]
               and re.fullmatch(r'(?i:От)\s+' + NAME, r['text'])]
    if len(senders) == 1:
        sender = senders[0]
        emit('student_name', re.sub(r'^От\s+', '', sender['text'], flags=re.I), [sender], 'explicit_sender_literal_case')
        h = sender['bbox'][3] - sender['bbox'][1]
        headers = [r for r in rows if r['page'] == sender['page']
                   and sender['bbox'][3] <= r['bbox'][1] < title['bbox'][1]
                   and abs(r['bbox'][0] - sender['bbox'][0]) <= 2*h]
        groups = []
        for r in headers:
            m = re.fullmatch(r'Студент(?:а|ки)\s+группы\s+([А-ЯЁа-яёA-Za-z0-9]+(?:[-/][А-ЯЁа-яёA-Za-z0-9]+)+)', r['text'], re.I)
            if m:
                groups.append(r)
                emit('group', m[1], [sender, r], 'explicit_student_group')
        dates = [(r, iso(r['text'])) for r in headers]
        dates = [(r, value) for r, value in dates if value != MISSING]
        if len(dates) == 1 and len(groups) == 1 and dates[0][0]['bbox'][1] >= groups[0]['bbox'][3]:
            emit('application_date', dates[0][1], [sender, groups[0], dates[0][0], title], 'unique_applicant_header_date')

    body = [r for r in rows if r['page'] == title['page'] and r['bbox'][1] > title['bbox'][3]]
    for parts in windows(body, relaxed=True):
        text = ' '.join(r['text'] for r in parts)
        # Optional printed year abbreviation between the range endpoints.
        pattern = r'\bакадемический\s+отпуск\s+[сc]\s+(' + DATE + r')\s*(?:г\.)?\s+по\s+(' + DATE + r')\s*(?:г\.)?'
        match = re.search(pattern, text, re.I)
        if match and re.search(r'\b(?:Прошу|оформить|предоставить)\b', text, re.I):
            start, end = iso(match[1]), iso(match[2])
            if MISSING not in (start, end) and start <= end:
                emit('leave_start', start, parts, 'explicit_leave_sentence_start')
                emit('leave_end', end, parts, 'explicit_leave_sentence_end')
        # Copy the reason literally; never infer pregnancy from an attachment.
        # The anchor's short connector can be a low-confidence symbol. Its
        # replacement is never exported: only the visible reason is copied.
        reason = re.search(r'\bПрошу\s+в\s+связи\s+(?:[сc]|[^\w\s]{1,2})\s+([^.;:]{3,100}?)\s+(?:оформить|предоставить)\s+академический\s+отпуск\b', text, re.I)
        if reason:
            emit('leave_reason', reason[1], parts, 'reason_before_leave_request')
    changes = []
    raw_keys = {'leave_start': 'start_date', 'leave_end': 'end_date', 'leave_reason': 'reason'}
    for key, options in proposals.items():
        raw = analysis.get('fields', {}).get(raw_keys.get(key, key), {})
        if (fields[key] != MISSING or raw.get('status') != 'not_found'
                or raw.get('value') is not None or bindings.get(key, {}).get('status') == 'conflict'
                or len({p['value'] for p in options}) != 1):
            continue
        result[key] = options[0]['value']
        evidence[key] = options[0]
        changes.append({'field': key, 'value': result[key], 'status': 'uncertain'})
    return result, evidence, changes
