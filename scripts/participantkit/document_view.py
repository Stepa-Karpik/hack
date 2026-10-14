"""Presentation geometry from the exact rectified pages used by OCR.

No extraction, expected-value lookup, semantic confidence or guessed boxes.
The existing result/audit remain untouched. Whole evidence regions can bind
multiple exported fields (e.g. two endpoints of a period).
"""
import base64
import io
import math
from PIL import Image

RAW_KEYS={'signature_present':'signature','seal_present':'stamp','study_start':'study_period',
    'study_end':'study_period','internship_start':'practice_period','internship_end':'practice_period',
    'leave_reason':'reason','leave_start':'start_date','leave_end':'end_date','supervisor_name':'supervisor'}

def build_document_view(pages,result,audit):
    encoded=[];regions=[];total=0
    for index,page in enumerate(pages[:10]):
        width,height=page.size
        image=page.convert('RGB').copy();image.thumbnail((1800,1800),Image.Resampling.LANCZOS)
        stream=io.BytesIO();image.save(stream,format='JPEG',quality=82,optimize=True)
        data=stream.getvalue();total+=len(data)
        if total>8*1024*1024:
            # A partial preview would obscure page/evidence indexing: fall back
            # to the original viewer rather than publishing a mismatched set.
            return {'pages':[],'regions':[],'reason':'preview_byte_budget'}
        encoded.append({'page':index,'width':width,'height':height,
            'image':'data:image/jpeg;base64,'+base64.b64encode(data).decode('ascii')})
    for key,value in result['fields'].items():
        if value is False or value is None or value=='не найдено':continue
        binding=audit.get('bindings',{}).get(key)
        raw=audit.get('analysis',{}).get('fields',{}).get(RAW_KEYS.get(key,key),{})
        source=binding if binding is not None else raw
        if not isinstance(source,dict) or source.get('status')=='conflict':continue
        evidence=source.get('evidence',{})
        if not isinstance(evidence,dict):continue
        space=evidence.get('coordinate_space','rectified_page_pixels')
        if space!='rectified_page_pixels':continue
        bbox=evidence.get('bbox');page_index=evidence.get('page')
        if (not isinstance(page_index,int) or isinstance(page_index,bool)
                or not 0<=page_index<len(encoded) or not isinstance(bbox,(list,tuple)) or len(bbox)!=4):continue
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in bbox):continue
        x1,y1,x2,y2=bbox;meta=encoded[page_index];w,h=meta['width'],meta['height']
        # Refuse out-of-page coordinates instead of silently inventing a crop.
        if not (0<=x1<x2<=w and 0<=y1<y2<=h):continue
        regions.append({'field':key,'page':page_index,'bbox':[x1/w,y1/h,x2/w,y2/h],
            'coordinate_space':'normalized_rectified_page','evidence_text':str(evidence.get('text','')),
            'status':source.get('status'),'semantic_confidence':None})
    return {'pages':encoded,'regions':regions,'coordinate_space':'rectified_page_pixels'}

def analyze_web_document(*args,**kwargs):
    # Import lazily to preserve the standalone contract API and inference path.
    from .service import analyze_document
    return analyze_document(*args,include_document_view=True,**kwargs)
