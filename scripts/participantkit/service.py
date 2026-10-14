"""Shared official analysis boundary; no manifest, benchmark or reference access."""
from pathlib import Path
import hashlib
import json
import time

if __package__:
    from .format_v1 import KINDS, validate, answer
    from .labeled_fields import extract_contract
else:
    from format_v1 import KINDS, validate, answer
    from labeled_fields import extract_contract

ROOT=Path(__file__).resolve().parents[2]
VERSION='official-contract-v7'


def load_config():
    return json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))


def check_request(document_type,questions):
    if document_type not in KINDS:
        raise ValueError('Choose one of the three supported official document types')
    if not isinstance(questions,list):
        raise ValueError('Questions must be a list')
    seen=set()
    for question in questions:
        if not isinstance(question,dict) or set(question)!={'question_id','question'}:
            raise ValueError('Question needs question_id and question')
        qid=question['question_id'];text=question['question']
        if not isinstance(qid,str) or not qid.strip() or qid in seen:
            raise ValueError('Question IDs must be unique nonempty strings')
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Question text must be nonempty')
        seen.add(qid)


def prepare_result(pages,analysis,document_type,questions,config=None,*,document_id='document',
                   crop_recovery=True,text_mark_guard=True,value_quote_recovery=True,gpu=True):
    """Apply the same qualified adapters to an existing full local analysis.

    Callers may reuse pages/analysis for repeated questions. No predictions are
    cached or matched by document_id. The input analysis is not mutated.
    """
    check_request(document_type,questions)
    if not isinstance(document_id,str) or not document_id.strip():
        raise ValueError('document_id must be a nonempty string')
    if analysis.get('type')!=KINDS[document_type]:
        raise ValueError('Analysis type does not match the requested official schema')
    if (crop_recovery or value_quote_recovery) and not pages:
        raise ValueError('Image rereads require original rectified pages')
    config=load_config() if config is None else config
    fields,evidence=extract_contract(analysis,document_type,config)
    recovery={'changes':[],'reason':'disabled'}
    value_recovery={'changes':[],'reason':'disabled'}
    guard={'applied':False,'reason':'disabled'}
    if crop_recovery:
        if __package__:from .crop_recovery import recover
        else:from crop_recovery import recover
        recovery=recover(pages,fields,evidence,gpu)
    if value_quote_recovery:
        if __package__:from .value_quote_recovery import recover
        else:from value_quote_recovery import recover
        value_recovery=recover(pages,analysis,fields,evidence,gpu)
    if text_mark_guard:
        if __package__:from .mark_guard import reject_printed_signature
        else:from mark_guard import reject_printed_signature
        guard=reject_printed_signature(analysis,fields,evidence)
    validation=validate(fields,document_type,config)
    answers=[{'question_id':q['question_id'],**answer(q['question'],fields,validation,config)} for q in questions]
    result={'document_id':document_id,'document_type':document_type,'fields':fields,
        'validation':validation,'answers':answers}
    audit={'bindings':evidence,'analysis':analysis,'crop_recovery':recovery,
        'mark_guard':guard,'value_quote_recovery':value_recovery}
    return result,audit


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
