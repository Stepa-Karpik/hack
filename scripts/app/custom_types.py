"""Document types added by the administrator in the constructor.

A type is described without training: phrases from its title, fields with the labels printed before the values
(«Номер:», «Дата выдачи» …) and the required marks. The CPU engine reads the page as usual (OCR + mark detector),
then this module finds the labels in the recognised lines and takes the value next to them.
"""
import re
import secrets
from datetime import date

MISSING = 'не найдено'
FIELD_KINDS = {'text': 'Текст', 'name': 'ФИО', 'date': 'Дата', 'number': 'Номер'}
MONTHS = {m: i + 1 for i, m in enumerate(['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
                                          'сентября', 'октября', 'ноября', 'декабря'])}
DATE = r'(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})|(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})'
NAME = r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?(?:\s+[А-ЯЁ][а-яё]+){1,2}|[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.'
LATIN = str.maketrans('aceopxykmhtbACEOPXYKMHTB', 'асеорхукмнтвАСЕОРХУКМНТВ')


def norm(text):
    text = str(text or '').translate(LATIN).casefold().replace('ё', 'е')
    return re.sub(r'\s+', ' ', re.sub(r'[«»"“”„]', '', text)).strip()


def new_key():
    return 'custom_' + secrets.token_hex(3)


def clean(raw, key=None):
    """Validate a constructor form -> stored config. Raises ValueError with a message for the admin."""
    title = re.sub(r'\s+', ' ', str(raw.get('title') or '')).strip()
    if not 3 <= len(title) <= 120:
        raise ValueError('Название типа — от 3 до 120 символов.')
    keywords = [re.sub(r'\s+', ' ', str(k)).strip() for k in raw.get('keywords') or [] if str(k).strip()]
    keywords = [k for k in keywords if len(k) >= 4][:10]
    if not keywords:
        raise ValueError('Добавьте хотя бы одну фразу из заголовка документа (не короче 4 символов).')
    fields = []
    for index, f in enumerate(raw.get('fields') or []):
        label = re.sub(r'\s+', ' ', str(f.get('label') or '')).strip()
        if not label:
            continue
        variants = [re.sub(r'\s+', ' ', str(v)).strip() for v in (f.get('variants') or [label]) if str(v).strip()]
        kind = f.get('kind') if f.get('kind') in FIELD_KINDS else 'text'
        fields.append({'key': f'{key or raw.get("key")}_f{index + 1}', 'label': label[:80], 'variants': variants[:8] or [label],
                       'kind': kind, 'required': bool(f.get('required', True))})
    if not fields and not raw.get('signature') and not raw.get('seal'):
        raise ValueError('Добавьте хотя бы одно поле или требование подписи/печати.')
    if len(fields) > 20:
        raise ValueError('Не больше 20 полей.')
    rule = re.sub(r'\s+', ' ', str(raw.get('rule') or '')).strip()[:20]
    return {'key': key or raw.get('key'), 'title': title, 'keywords': keywords, 'fields': fields,
            'signature': bool(raw.get('signature')), 'seal': bool(raw.get('seal')), 'rule': rule,
            'rule_text': re.sub(r'\s+', ' ', str(raw.get('rule_text') or '')).strip()[:500]}


def field_keys(config):
    keys = [f['key'] for f in config['fields']]
    return keys + (['signature_present'] if config.get('signature') else []) + (['seal_present'] if config.get('seal') else [])


def required_keys(config):
    keys = [f['key'] for f in config['fields'] if f.get('required', True)]
    return keys + (['signature_present'] if config.get('signature') else []) + (['seal_present'] if config.get('seal') else [])


def labels(config):
    return {f['key']: f['label'] for f in config['fields']}


def rule_id(config):
    return config.get('rule') or 'доп.'


def phrase_pattern(phrase):
    """Words of the phrase in order, endings free: «состав семьи» also finds «о составе семьи»."""
    words = [w for w in re.split(r'\W+', norm(phrase)) if w]
    stems = [re.escape(w[:max(3, len(w) - 2)] if len(w) > 4 else w) for w in words]
    return re.compile(r'(?<!\w)' + r'\w*\W+'.join(stems) + r'\w*')


def match(configs, lines, strict=False):
    """The custom type whose title phrase is printed in the upper half of the page (longest phrase wins), or None.
    strict (a built-in type was already recognised): a one-word phrase such as «справка» does not take the document over."""
    if not lines:
        return None
    bottom = max(l['bbox'][3] for l in lines)
    top_text = norm(' '.join(l['text'] for l in lines if l['bbox'][1] < bottom * 0.55))
    best, score = None, 0
    for config in configs:
        for phrase in config['keywords']:
            if strict and len(phrase.split()) < 2:
                continue
            if phrase_pattern(phrase).search(top_text) and len(phrase) > score:
                best, score = config, len(phrase)
    return best


def rows(lines):
    """Recognised boxes -> text rows in reading order, each with its own box."""
    ordered = sorted(lines, key=lambda l: (l.get('page', 0), round(l['bbox'][1] / 18), l['bbox'][0]))
    out = []
    for line in ordered:
        key = (line.get('page', 0), round(line['bbox'][1] / 18))
        if out and out[-1]['key'] == key:
            row = out[-1]
            row['text'] += ' ' + line['text']
            row['bbox'] = [min(row['bbox'][0], line['bbox'][0]), min(row['bbox'][1], line['bbox'][1]),
                           max(row['bbox'][2], line['bbox'][2]), max(row['bbox'][3], line['bbox'][3])]
            row['confidence'].append(line.get('confidence'))
        else:
            out.append({'key': key, 'text': line['text'], 'bbox': list(line['bbox']), 'confidence': [line.get('confidence')]})
    return out


def iso(text):
    m = re.search(DATE, norm(text))
    if not m:
        return None
    try:
        if m[1]:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        return date(int(m[6]), MONTHS[m[5]], int(m[4])).isoformat()
    except ValueError:
        return None


def shape(value, kind):
    value = re.sub(r'\s+', ' ', value).strip(' :—–-_.,;')
    if not value:
        return None
    if kind == 'date':
        return iso(value)
    if kind == 'number':
        m = re.search(r'№?\s*([A-Za-zА-Яа-яЁё]{0,4}[-/]?\d[\w/-]*)', value)
        return m[1] if m else None
    if kind == 'name':
        m = re.search(NAME, value)
        return m[0] if m else None
    return value[:200] if len(value) >= 2 else None


def label_at(row_text, variant):
    """(source row, end offset of the label in it) — case, ё and Latin look-alike tolerant; offset -1 when absent."""
    source = row_text.translate(LATIN)
    words = [re.escape(w).replace('е', '[её]') for w in norm(variant).split(' ') if w]
    m = re.search(r'[\s«»"]*'.join(words), source, re.I) if words else None
    return source, (m.end() if m else -1)


def extract(config, lines, marks, size):
    """fields, validation, statuses, confidence and normalised regions for a custom type."""
    width, height = size
    text_rows = rows(lines)
    all_variants = [norm(v) for f in config['fields'] for v in f['variants']]
    fields, statuses, confidence, regions = {}, {}, {}, []
    for f in config['fields']:
        value, used = None, None
        for i, row in enumerate(text_rows):
            for variant in f['variants']:
                source, end = label_at(row['text'], variant)
                if end < 0:
                    continue
                value = shape(source[end:], f['kind'])
                used = [row]
                if value is None and i + 1 < len(text_rows):  # value printed under the label
                    below = text_rows[i + 1]
                    if not any(v and v in norm(below['text']) for v in all_variants):
                        value = shape(below['text'], f['kind'])
                        used = [row, below]
                if value is not None:
                    break
            if value is not None:
                break
        fields[f['key']] = value if value is not None else MISSING
        statuses[f['key']] = 'found' if value is not None else 'not_found'
        confs = [c for r in used or [] for c in r['confidence'] if isinstance(c, (int, float))]
        confidence[f['key']] = round(float(min(confs)), 4) if value is not None and confs else None
        if value is not None:
            x0, y0 = min(r['bbox'][0] for r in used), min(r['bbox'][1] for r in used)
            x1, y1 = max(r['bbox'][2] for r in used), max(r['bbox'][3] for r in used)
            regions.append({'field': f['key'], 'page': 0, 'source': 'custom_label',
                            'bbox': [max(0, x0 / width), max(0, y0 / height), min(1, x1 / width), min(1, y1 / height)]})
    for key, mark in (('signature_present', 'signature'), ('seal_present', 'stamp')):
        if not config.get('seal' if mark == 'stamp' else 'signature'):
            continue
        found = (marks.get(mark) or {})
        box = (found.get('evidence') or {}).get('bbox')
        if found.get('value') is True and box and over_text(box, lines):
            found = {**found, 'value': False}  # a bold printed heading is not a handwritten signature
        fields[key] = found.get('value') is True
        statuses[key] = 'found' if fields[key] else 'not_found'
        confidence[key] = round(float(found.get('confidence') or 0), 4)
        box = (found.get('evidence') or {}).get('bbox')
        if fields[key] and box and (found.get('evidence') or {}).get('page', 0) == 0:
            regions.append({'field': key, 'page': 0, 'source': 'mark_detector',
                            'bbox': [box[0] / width, box[1] / height, box[2] / width, box[3] / height]})
    return {'fields': fields, 'validation': validate(config, fields), 'statuses': statuses,
            'confidence': confidence, 'regions': regions}


def over_text(box, lines):
    """True when most of the mark box is covered by a confidently read printed line (the detector fired on text)."""
    area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
    for line in lines:
        b = line['bbox']
        if (line.get('confidence') or 0) < 0.6 or len(re.sub(r'\W', '', line['text'])) < 6:
            continue
        w, h = min(box[2], b[2]) - max(box[0], b[0]), min(box[3], b[3]) - max(box[1], b[1])
        if w > 0 and h > 0 and w * h / area > 0.5:
            return True
    return False


def validate(config, fields):
    missing = [k for k in required_keys(config) if fields.get(k) in (False, None, MISSING)]
    return {'status': 'missing_fields' if missing else 'document_ok', 'missing_fields': missing,
            'sources': ['rule:' + rule_id(config)]}


def register(configs, config):
    """Make the stored types known to the rule answers, the assistant and the contract adapters of this process."""
    from scripts.participantkit import format_v1
    from scripts.unified import contract
    from scripts.app import workflow
    try:
        from scripts.assistant import core as assistant
    except Exception:  # the assistant is optional
        assistant = None
    for c in configs:
        format_v1.LABELS.update(labels(c))
        contract.KEYS[c['key']] = field_keys(c)
        config['requirements'][c['key']] = {rule_id(c): required_keys(c)}
        if c.get('rule_text'):
            config['rules'].setdefault(rule_id(c), c['rule_text'])
        workflow.TYPE_NAMES[c['key']] = c['title']
        if assistant is not None:
            assistant.TYPE_NAMES[c['key']] = c['title']
            assistant.FIELD_NAMES.update(labels(c))


def unregister(key, config):
    from scripts.unified import contract
    from scripts.app import workflow
    contract.KEYS.pop(key, None)
    config['requirements'].pop(key, None)
    workflow.TYPE_NAMES.pop(key, None)
