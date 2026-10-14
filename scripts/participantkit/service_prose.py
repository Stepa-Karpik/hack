"""Isolated official service revision with bounded missing-only leave recovery.

Previous service remains available unchanged. No dataset/reference access.
"""
from pathlib import Path
import hashlib
import time
from .service import check_request, load_config, prepare_result as legacy_prepare
from .format_v1 import KINDS, validate, answer
from .leave_prose_recovery import recover

VERSION = 'official-contract-prose-candidate-v8'


def prepare_result(pages, analysis, document_type, questions, config=None, *,
                   document_id='document', crop_recovery=True, text_mark_guard=True,
                   value_quote_recovery=True, gpu=True, prose_recovery=True):
    config = load_config() if config is None else config
    result, audit = legacy_prepare(pages, analysis, document_type, questions, config,
        document_id=document_id, crop_recovery=crop_recovery, text_mark_guard=text_mark_guard,
        value_quote_recovery=value_quote_recovery, gpu=gpu)
    if prose_recovery:
        fields, bindings, changes, rejected = recover(result['fields'], audit['bindings'], analysis)
        result['fields'] = fields
        result['validation'] = validate(fields, document_type, config)
        result['answers'] = [{'question_id': q['question_id'],
            **answer(q['question'], fields, result['validation'], config)} for q in questions]
        audit['bindings'] = bindings
        audit['prose_recovery'] = {'version': 'guarded-dates-v4', 'changes': changes, 'rejected': rejected}
    else:
        audit['prose_recovery'] = {'changes': [], 'reason': 'disabled'}
    return result, audit


def analyze_web_document(*args, **kwargs):
    return analyze_document(*args, include_document_view=True, **kwargs)

def analyze_document(data,filename,document_type,questions,*,document_id='document',gpu=True,include_document_view=False):
    """Analyze an upload locally; explicit type selection remains required.

    Returns result + audit + readable OCR. This is a Python API, not an HTTP
    deployment. The caller manages GPU serialization, upload limits and storage.
    """
    check_request(document_type,questions)
    if not isinstance(data,bytes) or not data:
        raise ValueError('Nonempty document bytes required')
    if not isinstance(filename,str) or Path(filename).suffix.lower() not in {'.png','.jpg','.jpeg','.pdf'}:
        raise ValueError('Supported uploads: PNG, JPG, JPEG, PDF')
    started=time.perf_counter()
    from dekanat.pipeline import analyze
    pages,analysis=analyze(data,filename,document_type=KINDS[document_type],gpu=gpu)
    result,audit=prepare_result(pages,analysis,document_type,questions,document_id=document_id,gpu=gpu)
    response={'version':VERSION,'result':result,'audit':audit,'ocr':analysis['ocr'],
        'input_sha256':hashlib.sha256(data).hexdigest(),'seconds':time.perf_counter()-started}
    if include_document_view:
        from .document_view import build_document_view
        response['document_view']=build_document_view(pages,result,audit)
    return response
