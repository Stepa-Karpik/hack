"""Reject weak signature candidates overlapping a recognized printed caption.

This rejects a candidate; it never proves document-wide absence/authenticity.
"""
import re
import math


def printed_caption(text):
    text=text.strip()
    return bool(re.fullmatch(r'подпись\s+(?:сотрудника|студента|руководителя)\s*:',text,re.I)
        or re.fullmatch(r'СПРАВКА\s+(?:ОБ?\s+)?[А-ЯЁ\s]{6,60}',text))


def overlap(a,b):
    if not isinstance(a,(list,tuple)) or not isinstance(b,(list,tuple)) or len(a)!=4 or len(b)!=4:
        return 0
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in [*a,*b]):
        return 0
    area_a=(a[2]-a[0])*(a[3]-a[1]);area_b=(b[2]-b[0])*(b[3]-b[1])
    if area_a<=0 or area_b<=0 or max(area_a,area_b)/min(area_a,area_b)>1.8:
        return 0
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))/min(area_a,area_b)


def reject_printed_signature(analysis,fields,evidence):
    field=analysis.get('fields',{}).get('signature',{})
    detection=field.get('evidence') or {}
    if fields.get('signature_present') is not True or field.get('status')!='uncertain':
        return {'applied':False,'reason':'no_weak_positive'}
    if detection.get('method')!='finetuned_yolov8n':
        return {'applied':False,'reason':'unsupported_detector'}
    for line in analysis.get('ocr',{}).get('lines',[]):
        score=line.get('confidence',0)
        if not isinstance(score,(int,float)) or not .7<=score<=1:
            continue
        if line.get('page')!=detection.get('page') or not printed_caption(line.get('text','')):
            continue
        coverage=overlap(detection.get('bbox'),line.get('bbox'))
        if coverage>=.9:
            fields['signature_present']=False
            evidence['signature_present']={'status':'uncertain','source':'weak_printed_candidate_rejection',
                'semantic_confidence':None,'candidate':field,'printed_line':line,'overlap_min_area':coverage,
                'note':'Rejected weak text-shaped candidate; no conclusive document-wide absence or authenticity claim.'}
            return {'applied':True,'reason':'recognized_printed_caption','overlap_min_area':coverage}
    return {'applied':False,'reason':'no_supported_printed_overlap'}
