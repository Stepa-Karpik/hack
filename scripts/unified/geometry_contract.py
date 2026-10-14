"""Optional geometry abstention. Scalar predictions are never changed.

Malformed coordinates are discarded, not reordered/clamped or reconstructed.
Original strict errors and raw geometry remain audit data. No references read.
"""
import copy
import json
import math
from scripts.unified.contract import KEYS, parse


def parse_abstaining(text):
    try:
        return parse(text),{'strict_accepted':True,'strict_error':None,'abstentions':[]}
    except (ValueError,TypeError) as strict:
        strict_error=str(strict)
    raw=json.loads(text)
    if not isinstance(raw,dict) or set(raw)!={'document_type','fields','boxes'}:
        raise ValueError('Geometry abstention requires a complete typed record')
    kind=raw['document_type']
    if not isinstance(kind,str) or kind not in KEYS:raise ValueError('Unknown schema')
    if any(not isinstance(raw.get(k),dict) or set(raw[k])!=set(KEYS[kind]) for k in ['fields','boxes']):
        raise ValueError('Geometry abstention cannot create omitted fields or boxes')
    safe=copy.deepcopy(raw);abstentions=[]
    for key,bbox in raw['boxes'].items():
        if bbox is None:continue
        valid=(isinstance(bbox,list) and len(bbox)==4 and
               all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1000 for v in bbox) and
               bbox[0]<bbox[2] and bbox[1]<bbox[3])
        absent=raw['fields'][key] is None or raw['fields'][key] is False
        if not valid or absent:
            safe['boxes'][key]=None
            abstentions.append({'field':key,'raw_box':bbox,
                                'reason':'field_absent' if absent else 'invalid_coordinates'})
    accepted=parse(json.dumps(safe,ensure_ascii=False))
    if accepted['fields']!=raw['fields']:raise AssertionError('Scalar values must remain exact')
    return accepted,{'strict_accepted':False,'strict_error':strict_error,'abstentions':abstentions}
