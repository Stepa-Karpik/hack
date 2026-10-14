"""Literal field binding for the official contract; no reference-data dependency.

This adapter is separate from legacy extraction. An explicit label can resolve
an old classifier conflict, but disagreements between two explicit labels stay
missing. OCR/source confidence is not a probability of semantic correctness.
"""
import re
if __package__:
    from .format_v1 import LABELS, MISSING, iso, fields_from_v21, norm
else:
    from format_v1 import LABELS, MISSING, iso, fields_from_v21, norm

DATES = {'study_start', 'study_end', 'internship_start', 'internship_end',
         'leave_start', 'leave_end', 'issue_date', 'application_date'}


def label_match(text):
    for key, label in sorted(LABELS.items(), key=lambda item: -len(item[1])):
        match = re.match(r'^\s*' + re.escape(label) + r'(?:\s*:\s*|\s*$)', text, re.I)
        if match:
            return key, text[match.end():].strip()
    return None


def _box(line):
    box = line.get('bbox')
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = map(float, box)
        return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None
    except (ValueError, TypeError):
        return None


def candidates(lines):
    """Read inline values plus bounded, geometrically adjacent fragments.

    Other labels are hard boundaries. Captions, footer prose and IDs are never
    borrowed as continuations. No document ID or anticipated value is consulted.
    """
    output = {}
    for line in lines:
        match = label_match(line.get('text', ''))
        if not match or match[0].endswith('_present'):
            continue
        key, literal = match
        box = _box(line)
        parts = [line]
        if box:
            height = box[3] - box[1]
            neighbors = []
            for other in lines:
                if other is line or other.get('page', 0) != line.get('page', 0):
                    continue
                ob = _box(other)
                text = other.get('text', '').strip()
                if not ob or not text or label_match(text):
                    continue
                # Same printed row; handles an isolated leading date digit.
                same = abs((ob[1]+ob[3]-box[1]-box[3])/2) <= height * .5
                right = ob[0] >= box[2] - height * .2
                # A single wrapped row below an otherwise empty label.
                below = not literal and 0 <= ob[1]-box[3] <= height * .7 and abs(ob[0]-box[0]) <= height*2
                if not ((same and right) or below):
                    continue
                if ':' in text or re.search(r'подпись|печать|идентификатор|вымышлен|макет', text, re.I):
                    continue
                # Do not cross another field's row to borrow its value.
                boundary = any(label_match(t.get('text','')) and t is not line
                               and t.get('page',0)==line.get('page',0) and _box(t)
                               and box[1] < _box(t)[1] <= ob[3] for t in lines)
                if not boundary:
                    neighbors.append(other)
            neighbors.sort(key=lambda item: (0 if abs((_box(item)[1]+_box(item)[3]-box[1]-box[3])/2) <= height*.5 else 1, _box(item)[0]))
            parts += neighbors
            literal = ' '.join([literal] + [p['text'].strip() for p in neighbors]).strip()
        value = iso(literal) if key in DATES else re.sub(r'\s+', ' ', literal).strip()
        if not value or re.fullmatch(r'[\s_.—–-]+', value):
            value = MISSING
        if key == 'course' and value != MISSING and not re.fullmatch(r'\d+', value):
            value = MISSING
        output.setdefault(key, []).append({'value': value, 'literal': literal,
            'status': 'uncertain' if value != MISSING else 'not_found',
            'source': 'ocr_full_label', 'semantic_confidence': None,
            'parts': [{k: p.get(k) for k in ('text','bbox','page','confidence')} for p in parts]})
    return output


def extract_contract(analysis, document_type, config):
    fields = fields_from_v21(analysis, document_type, config)
    bindings = candidates(analysis.get('ocr', {}).get('lines', []))
    evidence = {}
    for key, proposals in bindings.items():
        if key not in fields:
            continue
        values = {norm(p['value']) for p in proposals}
        if len(values) != 1:
            fields[key] = MISSING
            evidence[key] = {'status': 'conflict', 'proposals': proposals}
        elif fields[key] != MISSING and proposals[0]['value'] != MISSING and norm(fields[key]) != norm(proposals[0]['value']):
            # The legacy pipeline already applied bounded numeric/quote rereads.
            # First-pass label OCR cannot replace a non-conflicting refinement.
            evidence[key] = {'status': 'retained_existing', 'value': fields[key],
                'reason': 'nonempty_existing_has_priority', 'proposals': proposals}
        else:
            fields[key] = proposals[0]['value']
            evidence[key] = proposals[0]
    return fields, evidence
