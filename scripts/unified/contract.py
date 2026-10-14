"""Strict experimental output contract, independent of OCR and benchmark answers."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'configs/participant_v1.json').read_text(encoding='utf-8'))
KEYS = {kind: [key for group in groups.values() for key in group]
        for kind, groups in CONFIG['requirements'].items()}
MARKS = {'signature_present', 'seal_present'}


def prompt():
    return ('Read this Russian student document directly from the image. Return ONLY JSON '
            'with document_type, fields, boxes. Allowed types and their field keys: '
            + json.dumps(KEYS, ensure_ascii=False, separators=(',', ':'))
            + '. Copy visible text exactly; dates YYYY-MM-DD. Missing or conflicting text '
            'must be null. Marks signature_present/seal_present are boolean: printed '
            'captions, empty signature lines and logos are not handwritten signatures '
            'or seals. Never invent values. boxes contains one [x1,y1,x2,y2] per visible '
            'field, integer coordinates 0..1000 relative to the full image, or null. '
            'Include every required key for the detected type. No explanations.')


def parse(text):
    """Reject malformed outputs, unexpected fields, non-booleans and invalid boxes."""
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'document_type', 'fields', 'boxes'}:
        raise ValueError('Invalid document object')
    kind = value['document_type']
    if not isinstance(kind, str) or kind not in KEYS:
        raise ValueError('Unsupported document type')
    fields, boxes = value['fields'], value['boxes']
    if not isinstance(fields, dict) or set(fields) != set(KEYS[kind]):
        raise ValueError('Incomplete or unexpected field keys')
    if not isinstance(boxes, dict) or set(boxes) != set(fields):
        raise ValueError('Incomplete or unexpected box keys')
    for key, literal in fields.items():
        if key in MARKS:
            if type(literal) is not bool:
                raise ValueError('Marks must be boolean')
        elif literal is not None and (not isinstance(literal, str) or not literal.strip()):
            raise ValueError('Text values must be nonempty strings or null')
        box = boxes[key]
        if box is not None:
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(n) not in (int, float) or not math.isfinite(n)
                           or not 0 <= n <= 1000 for n in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                raise ValueError('Invalid image-relative box')
            if literal is None or literal is False:
                raise ValueError('Missing values cannot have evidence boxes')
    return value


def json_schema():
    """Constrain syntax and field membership, never the expected document values."""
    variants=[]
    for kind, keys in KEYS.items():
        fields={k:{'type':'boolean'} if k in MARKS else {'type':['string','null']} for k in keys}
        boxes={k:{'anyOf':[{'type':'null'},{'type':'array','items':{'type':'number'},
                         'minItems':4,'maxItems':4}]} for k in keys}
        variants.append({'type':'object','properties':{
            'document_type':{'type':'string','enum':[kind]},
            'fields':{'type':'object','properties':fields,'required':keys,'additionalProperties':False},
            'boxes':{'type':'object','properties':boxes,'required':keys,'additionalProperties':False}},
            'required':['document_type','fields','boxes'],'additionalProperties':False})
    return {'anyOf':variants}


def official_result(prediction, questions=()):
    """Use the same explicit rules; all VLM outputs remain semantically uncertain."""
    from scripts.participantkit.format_v1 import validate, answer
    kind = prediction['document_type']
    fields = {key: 'не найдено' if val is None else val
              for key, val in prediction['fields'].items()}
    validation = validate(fields, kind, CONFIG)
    return {'document_type': kind, 'fields': fields, 'validation': validation,
            'answers': [dict(question_id=q['question_id'],
                             **answer(q['question'], fields, validation, CONFIG)) for q in questions],
            'audit': {key: {'status': 'uncertain', 'semantic_confidence': None,
                            'source': 'unified_vlm', 'bbox': prediction['boxes'][key],
                            'coordinate_space': 'input_image_0_1000',
                            'geometry_verified': False} for key in fields}}
