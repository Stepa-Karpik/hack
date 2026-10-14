"""Bounded literal name rereads by the same native model, without dictionaries."""
import math
import re

from scripts.participantkit.format_v1 import LABELS
from scripts.unified.spotting_name_crops import regions

FIELDS = {'student_name', 'supervisor_name'}


def one_edit(a, b):
    if abs(len(a)-len(b)) > 1 or a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(short == long[:i]+long[i+1:] for i in range(len(long)))


def accept(old, audit, readings):
    """Only one surname edit after a fixed prefix, with exact given-name tail.

    Found/conflict/missing/foreign-source fields are preserved. Two scale views
    are correlated observations, not calibrated probabilities.
    """
    if audit.get('status') != 'uncertain' or audit.get('source') != 'single_network_ocr_explicit_label':
        return None, 'preserved_status_or_source'
    if not isinstance(old, str) or len(readings) != 2 or any(not isinstance(v, str) for v in readings):
        return None, 'missing_or_incomplete'
    values = [' '.join(v.split()) for v in readings]
    if values[0] != values[1] or not values[0]:
        return None, 'reread_disagreement'
    proposal = values[0]
    if proposal == old:
        return None, 'unchanged'
    parts, previous = proposal.split(), old.split()
    if len(parts) != 3 or len(previous) != 3 or parts[1:] != previous[1:]:
        return None, 'name_tail_changed'
    if any(not all(c.isalpha() or c == '-' for c in token) for token in parts+previous):
        return None, 'not_literal_name'
    if len(parts[0]) < 4 or len(previous[0]) < 4 or parts[0][:3] != previous[0][:3]:
        return None, 'surname_prefix_changed'
    if not one_edit(parts[0], previous[0]):
        return None, 'surname_edit_budget'
    return proposal, 'bounded_surname_consensus'


def value_crop(image, spotting, field, *, truncated=False):
    if field not in FIELDS or truncated:
        return None, {'reason': 'unsupported_or_truncated'}
    pattern = re.compile(r'^'+re.escape(LABELS[field])+r'\s*:', re.I)
    found = [r for r in regions(spotting) if pattern.match(r['text'])]
    evidence = {'reason': 'ambiguous_or_missing_label', 'regions': found}
    if len(found) != 1:
        return None, evidence
    x1, y1, x2, y2 = found[0]['box_0_1000']
    box = [max(0, math.floor(x1*image.width/1000)-6), max(0, math.floor(y1*image.height/1000)-6),
           min(image.width, math.ceil(x2*image.width/1000)+6), min(image.height, math.ceil(y2*image.height/1000)+6)]
    evidence['line_bbox_pixels'] = box
    if not 12 <= box[3]-box[1] <= 160 or not 100 <= box[2]-box[0] <= 2000:
        evidence['reason'] = 'crop_budget'
        return None, evidence
    import cv2
    import numpy as np
    from PIL import Image
    from scripts.participantkit.value_quote_recovery import colon_cuts
    gray = cv2.cvtColor(np.asarray(image.crop(box).convert('RGB')), cv2.COLOR_RGB2GRAY)
    cuts = colon_cuts(gray)
    evidence['colon_candidates'] = cuts
    if len(cuts) != 1 or gray.shape[1]-cuts[0] <= 60:
        evidence['reason'] = 'ambiguous_or_missing_colon'
        return None, evidence
    evidence['value_bbox_pixels'] = [box[0]+cuts[0]+1, box[1], box[2], box[3]]
    evidence['reason'] = 'prepared'
    return Image.fromarray(gray[:, cuts[0]+1:]), evidence
