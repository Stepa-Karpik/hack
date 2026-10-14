"""Bounded image rereads for official labeled fields. No expected-value lookup."""
import re
import time
if __package__:
    from .format_v1 import LABELS, MONTHS, MISSING, iso, norm
    from .labeled_fields import DATES
else:
    from format_v1 import LABELS, MONTHS, MISSING, iso, norm
    from labeled_fields import DATES


def quoted(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[^«»]+\s+«[^«»]{2,180}»', value.strip()))


def parsed_reading(key, text):
    # Quote recognizer sometimes reads the label's colon as a guillemet.
    prefix=re.match(r'^\s*'+re.escape(LABELS[key])+r'\s*[:«]\s*', text, re.I)
    if not prefix:
        return None
    value=text[prefix.end():].strip()
    if key in DATES:
        value=iso(value)
        return None if value==MISSING else value
    return value if key in {'university','organization'} and quoted(value) else None


def accepted_reading(key, literal, readings):
    """Two variants are correlated evidence, never calibrated confidence."""
    if len(readings)!=2 or any(len(items)!=1 for items in readings):
        return None
    threshold=.65 if key in DATES else .50
    if any(not 0 <= item[1] <= 1 or item[1]<threshold for items in readings for item in items):
        return None
    values=[parsed_reading(key,items[0][0]) for items in readings]
    if not all(values) or norm(values[0])!=norm(values[1]):
        return None
    if key in DATES:
        # Existing suffix must already contain a month and four-digit year.
        suffix=re.fullmatch(r'\s*('+ '|'.join(MONTHS)+r')\s+(\d{4})(?:\s+года)?\s*',literal,re.I)
        if not suffix:
            return None
        year,month,_=map(int,values[0].split('-'))
        if year!=int(suffix[2]) or month!=MONTHS[suffix[1].casefold()]:
            return None
    return values[0]


def recover(pages,fields,evidence,gpu=True):
    import cv2
    import numpy as np
    from dekanat.ocr import get_reader,quote_state
    started=time.perf_counter()
    changes=[];attempts=[]
    for key,binding in evidence.items():
        if len(attempts)>=12 or binding.get('status')=='conflict':
            continue
        literal=binding.get('literal','')
        is_date=key in DATES and fields[key]==MISSING and bool(re.fullmatch(
            r'\s*(?:'+ '|'.join(MONTHS)+r')\s+\d{4}(?:\s+года)?\s*',literal,re.I))
        is_quote=key in {'university','organization'} and fields[key]!=MISSING and not quoted(fields[key])
        if not (is_date or is_quote):
            continue
        # Do not reread an unresolved set of explicit duplicate labels.
        parts=binding.get('parts') or binding.get('proposals',[{}])[0].get('parts',[])
        if not parts or len({p.get('page') for p in parts})!=1:
            continue
        page_index=parts[0]['page']
        if not isinstance(page_index,int) or not 0<=page_index<len(pages):
            continue
        boxes=[p.get('bbox') for p in parts]
        if any(not isinstance(box,(list,tuple)) or len(box)!=4 for box in boxes):
            continue
        page=pages[page_index]
        x1=max(0,int(min(b[0] for b in boxes))-10); y1=max(0,int(min(b[1] for b in boxes))-8)
        x2=min(page.width,int(max(b[2] for b in boxes))+16); y2=min(page.height,int(max(b[3] for b in boxes))+8)
        if x2<=x1 or y2<=y1 or y2-y1>160:
            continue
        if is_quote:
            weights=quote_state()
            if weights is None:
                continue
            reader=get_reader(gpu,weights,detector=False)
        else:
            reader=get_reader(gpu,False,detector=False)
        crop=cv2.cvtColor(np.asarray(page)[y1:y2,x1:x2],cv2.COLOR_RGB2GRAY)
        readings=[]
        for scale in [1,2]:
            image=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC) if scale==2 else crop
            prediction=reader.recognize(image,detail=1,decoder='greedy',batch_size=1)
            readings.append([[str(p[1]),float(p[2])] for p in prediction])
        value=accepted_reading(key,literal,readings)
        attempt={'key':key,'page':page_index,'bbox':[x1,y1,x2,y2],
            'readings':readings,'accepted':value,'before':fields[key],
            'recognizer':'selected_guillemet' if is_quote else 'base_cyrillic',
            'variants':['gray_native','gray_cubic_2x']}
        attempts.append(attempt)
        if value is not None:
            fields[key]=value
            evidence[key]={'status':'uncertain','source':'bounded_image_reread',
                'semantic_confidence':None,'source_confidence':min(items[0][1] for items in readings),
                'value':value,'previous':binding,'reread':attempt}
            changes.append(key)
    return {'seconds':time.perf_counter()-started,'attempts':attempts,'changes':changes}
