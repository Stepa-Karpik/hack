"""Turn one native reader row into the app's document result (no extra NN calls).

Same post-processing as the local native page: literal layout v1+v2, study
prose recovery, rule validation. Adds the document type detected from the
model's own title when the user chose "auto", and a per-field confidence from
the decoder's token probabilities (minimum over the value's tokens).
"""
import re

from scripts.unified.contract import KEYS, MARKS, official_result
from scripts.unified.literal_layout import separate_empty_labels, separate_label_runs
from scripts.unified.prose_binding import recover
from scripts.unified.text_binding import bind

# A value is flagged for review when the minimum probability of its tokens is below the
# threshold. Chosen on v4b val/test (8/10 wrong values flagged, 11% of correct ones) and
# checked on the organizer kit (3/3 wrong, 12% of correct). Names are the risky fields.
REVIEW_THRESHOLDS = {'student_name': 0.8, 'supervisor_name': 0.8}
REVIEW_THRESHOLD = 0.4


def _value_span(text, candidate):
    span = candidate.get('ocr_text_span')
    if not span:
        return None
    start, end = span
    literal = (candidate.get('literal') or candidate.get('value') or '').strip()
    if literal:
        found = text.rfind(literal, start, end)
        if found >= 0:
            return found, found + len(literal)
    return start, end


def field_confidence(text, audit_entry, token_confidence):
    """Minimum token probability over the characters of the value, or None."""
    if not token_confidence or not audit_entry:
        return None
    spans = [s for s in (_value_span(text, c) for c in audit_entry.get('candidates') or []) if s]
    if not spans:
        return None
    values, previous = [], 0
    for end, prob in token_confidence:
        for start, stop in spans:
            if previous < stop and end > start:
                values.append(prob)
                break
        previous = end
    return min(values) if values else None


def analyze(row, kind):
    raw = row['raw_ocr']
    text = raw
    edits = []
    binding = row['binding']
    if not row['token_budget_reached']:
        text, edits = separate_empty_labels(text)
        text, more = separate_label_runs(text)
        edits += more
        binding = bind(text)
    before = binding
    binding = recover(text, binding, truncated=row['token_budget_reached'])
    recovered = [k for k, v in binding['fields'].items() if v is not None and before['fields'].get(k) is None]
    detected = binding['document_type']
    if kind == 'auto':
        kind = detected or 'study_certificate'
    matched = detected == kind
    fields = dict(binding['fields']) if matched else {key: None for key in KEYS[kind]}
    audit = dict(binding['audit']) if matched else {
        key: {'status': 'not_found', 'source': 'native_title_mismatch'} for key in fields}
    confidence, review = {}, {}
    for key in fields:
        if key in MARKS:
            continue
        entry = audit.get(key) or {}
        conf = field_confidence(text, entry, row.get('token_confidence'))
        confidence[key] = None if conf is None else round(conf, 4)
        limit = REVIEW_THRESHOLDS.get(key, REVIEW_THRESHOLD)
        uncertain = entry.get('status') == 'conflict' or (conf is not None and conf < limit)
        review[key] = bool(fields[key] is not None and uncertain)
    scores = row['graphic_scores_uncalibrated']
    patch = row.get('mark_patch') or {}
    mark_boxes = {}
    for key in MARKS & set(fields):
        global_present = row['graphic_prediction'][key]
        score = scores[0 if key == 'signature_present' else 1]
        p = patch.get(key)
        if p is None:
            present, source = global_present, 'shared_visual_graphic_readout'
        else:
            # rule chosen on validation: 'patch' (patch head decides) or 'or' (either head)
            present = p['present'] or (p.get('rule') == 'or' and global_present)
            source = 'shared_visual_patch_head' if p['present'] else 'shared_visual_graphic_readout'
            score = max(score, p['score']) if present else min(score, p['score'])
            if p['present']:
                mark_boxes[key] = p['box']
        fields[key] = present
        audit[key] = {'status': 'uncertain', 'source': source, 'score': score,
                      'global_score': scores[0 if key == 'signature_present' else 1], 'patch_score': p['score'] if p else None}
        confidence[key] = round(score if present else 1 - score, 4)
    result = official_result({'document_type': kind, 'fields': fields, 'boxes': {k: None for k in fields}})
    return {
        'document_type': kind, 'detected_type': detected, 'type_matches': matched,
        'fields': result['fields'], 'validation': result['validation'],
        'audit': audit, 'confidence': confidence, 'review': review,
        'recovered_from_prose': recovered if matched else [], 'mark_boxes': mark_boxes,
        'ocr_text': text, 'raw_ocr': raw, 'layout_edits': edits,
        'model': {'decoder': row.get('decoder'), 'seconds': round(row['seconds'], 2),
                  'token_budget_reached': row['token_budget_reached'], 'visual_passes': row['shared_visual_passes']},
    }


FAST_REVIEW_THRESHOLD = 0.5  # CPU engine: recognizer confidence of the value line


def analyze_fast(row, kind, custom=None):
    """Same analysis shape as analyze(), from the CPU engine (fields, statuses, geometry already resolved)."""
    custom = custom or {}
    detected = row.get('detected_type')
    if kind == 'auto':
        kind = detected or 'study_certificate'
    matched = detected == kind and bool(row.get('fields'))
    if matched:
        fields, validation = row['fields'], row['validation']
    elif kind in custom:  # a constructor type that was not recognised on the page
        from scripts.app import custom_types
        fields = {key: False if key in MARKS else 'не найдено' for key in custom_types.field_keys(custom[kind])}
        validation = custom_types.validate(custom[kind], fields)
    else:
        result = official_result({'document_type': kind, 'fields': {key: None for key in KEYS[kind]},
                                  'boxes': {key: None for key in KEYS[kind]}})
        fields, validation = result['fields'], result['validation']
    statuses = row.get('statuses') or {}
    confidence = dict(row.get('confidence') or {}) if matched else {}
    review = {}
    for key, value in fields.items():
        if key in MARKS:
            continue
        conf = confidence.get(key)
        review[key] = bool(value not in (None, 'не найдено') and (statuses.get(key) == 'conflict'
                                                                  or (conf is not None and conf < FAST_REVIEW_THRESHOLD)))
    mark_boxes = {r['field']: r['bbox'] for r in row.get('regions') or [] if r['field'] in MARKS and r.get('kind') != 'missing'} if matched else {}
    audit = {key: {'status': statuses.get(key) or 'not_found', 'source': 'cpu_fast_engine'} for key in fields}
    return {
        'document_type': kind, 'detected_type': detected, 'type_matches': matched,
        'fields': fields, 'validation': validation, 'audit': audit, 'confidence': confidence, 'review': review,
        'recovered_from_prose': [], 'mark_boxes': mark_boxes, 'ocr_text': row.get('ocr_text', ''),
        'raw_ocr': row.get('ocr_text', ''), 'layout_edits': [], 'engine': 'cpu-fast',
        'model': {'decoder': 'cpu-fast', 'seconds': row.get('seconds', 0), 'token_budget_reached': False, 'visual_passes': 1},
    }


def counts(analysis):
    fields = analysis['fields']
    found = sum(1 for v in fields.values() if v not in ('не найдено', False, None))
    return found, len(fields)


SLUG_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'


def new_slug():
    import secrets
    parts = (9, 7, 5)
    return '-'.join(''.join(secrets.choice(SLUG_ALPHABET) for _ in range(n)) for n in parts)


def valid_slug(slug):
    return re.fullmatch(r'[0-9a-z]{9}-[0-9a-z]{7}-[0-9a-z]{5}', slug or '') is not None
