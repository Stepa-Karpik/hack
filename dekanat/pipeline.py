import time
import json
from pathlib import Path
from .schema import SCHEMAS,ROOT
from .io import read_pages
from .ocr import recognize,refine_uncertain,recover_course,refine_numeric_fields,selection_state,recover_quote_fields,quote_state
from .extraction import detect_type,extract,type_review_reason
from .visual import classify
from .reasoning import answer
from .preprocessing import rectify_page,flatten_lighting
from .field_validation import validate_fields,require_type_review
from .slots import fill_missing_slots
from .pdf_text import enrich_pdf

ANALYSIS_VERSION="2026-10-11-official-v21"

def analyze(data,filename,document_type="auto",gpu=True,retry=True,finetuned=True,photo=True,quote_weights=None,orientation=True,native_pdf=True):
    started=time.perf_counter()
    pages=[rectify_page(page,photo=photo) for page in read_pages(data,filename)]
    preprocessing=[page.info["preprocessing"] for page in pages]
    ocr_pages=[]
    for page,metadata in zip(pages,preprocessing):
        corrected,light=flatten_lighting(page) if photo else (page,{"applied":False})
        metadata["lighting"]=light;ocr_pages.append(corrected)
    ocr=recognize(ocr_pages,gpu=gpu,retry=retry and not orientation,finetuned=finetuned)
    orientation_result = None
    if orientation:
        from .orientation import recover
        orientation_result = recover(pages, ocr_pages, ocr,
                                     lambda images: recognize(images, gpu=gpu, retry=False, finetuned=finetuned), document_type)
        preprocessing = [page.info["preprocessing"] for page in pages]
        if retry:
            refine_uncertain(ocr_pages, ocr, gpu, finetuned)
    kind=detect_type(ocr["lines"]) if document_type=="auto" else document_type
    if kind not in SCHEMAS:
        return pages,{"version":ANALYSIS_VERSION,"type":None,"fields":{},"ocr":ocr,"preprocessing":preprocessing,"orientation":orientation_result,"seconds":time.perf_counter()-started,
                      "error":"Тип документа не определён. Выберите один из трёх типов вручную."}
    fields=extract(ocr["lines"],kind,ROOT/"models"/"fields.joblib")
    quote_model = quote_weights if quote_weights is not None else quote_state() if finetuned is not False else None
    if quote_model:
        ocr["quote_recovery"] = recover_quote_fields(ocr_pages, ocr["lines"], fields, kind, gpu, quote_model)
        ocr["retries"] += ocr["quote_recovery"]["attempts"]
    if kind=="leave" and fields["course"]["value"] is None:
        recovered=recover_course(ocr_pages,ocr["lines"],gpu,finetuned)
        if recovered:
            ocr["lines"].append(recovered);ocr["retries"]+=1
            fields=extract(ocr["lines"],kind,ROOT/"models"/"fields.joblib")
            if recovered.get('requires_review') and fields['course']['status']=='found':
                fields['course']['status']='uncertain'
                fields['course'].setdefault('validation',[]).append({'rule':'weak_recovered_digit','reason':'Цифра найдена в ограниченном поле курса, но OCR недостаточно уверен; нужна проверка.'})
    selection=selection_state()
    cascade=finetuned=="cascade" or (finetuned is True and selection.get("enabled") and selection.get("mode")=="numeric_cascade")
    if cascade and (ROOT/"models"/"ocr_cyrillic.pt").exists():
        ocr["numeric_refinements"]=refine_numeric_fields(ocr_pages,fields,kind,gpu)
    fields.update(classify(pages,SCHEMAS[kind]["visual"],ROOT/"models"/"visual.pt",gpu))
    slot_recovery=fill_missing_slots(ocr['lines'],fields,kind)
    native_pdf_result=enrich_pdf(data,filename,fields,kind,ROOT/'models/fields.joblib',orientation=orientation_result,preprocessing=preprocessing) if native_pdf else {'applied':False,'changes':[],'reason':'disabled'}
    field_validation=validate_fields(fields)
    type_review=type_review_reason(ocr['lines'],kind) if document_type=='auto' else None
    field_validation['changes'].extend(require_type_review(fields,type_review))
    return pages,{"version":ANALYSIS_VERSION,"type":kind,"fields":fields,"ocr":ocr,"preprocessing":preprocessing,"orientation":orientation_result,"seconds":time.perf_counter()-started,
                  "field_validation":field_validation,"type_review":type_review,"slot_recovery":slot_recovery,"native_pdf":native_pdf_result,
                  "ocr_mode":"numeric_cascade" if cascade else "experimental_recognizer" if isinstance(finetuned,Path) else "global_candidate" if finetuned=="candidate" else "baseline_or_selected"}

def respond(analysis,question,policy):
    if not analysis["type"]:
        return {"status":"no_answer","answer":analysis["error"],"sources":[]}
    response=answer(question,analysis["type"],analysis["fields"],policy)
    warnings=list(dict.fromkeys(warning for page in analysis.get("preprocessing",[])
                               for warning in page.get("quality",{}).get("warnings",[])))
    if response["status"]=="complete" and warnings:
        response={**response,"status":"insufficient",
                  "answer":"Извлечённые сведения соответствуют проверенным требованиям, но качество изображения требует проверки или пересъёмки. "+" ".join(warnings)}
    return response

