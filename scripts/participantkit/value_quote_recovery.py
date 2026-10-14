"""Selected quote reader on values separated by visible colon components."""
import re
import time
if __package__:
    from .format_v1 import LABELS,MISSING,norm
    from .crop_recovery import quoted
else:
    from format_v1 import LABELS,MISSING,norm
    from crop_recovery import quoted


def colon_cuts(gray):
    import cv2
    mask=(gray<150).astype('uint8')
    _,_,stats,centroids=cv2.connectedComponentsWithStats(mask,8)
    h,w=gray.shape
    dots=[(s,c) for s,c in zip(stats[1:],centroids[1:])
        if 1<=s[4]<=max(16,h*h*.035) and s[2]<=max(5,h*.16) and s[3]<=max(5,h*.16)]
    cuts=set()
    for s,c in dots:
        for t,d in dots:
            if .12*h<d[1]-c[1]<.5*h and abs(c[0]-d[0])<=2 and .5<=s[4]/max(t[4],1)<=2.1:
                x=int(max(s[0]+s[2],t[0]+t[2]))
                if .10*w<x<.70*w:cuts.add(x)
    return sorted(cuts)


def accepted_value(before,readings):
    if quoted(before) or before==MISSING or len(readings)!=2 or any(len(r)!=1 for r in readings):
        return None
    values=[' '.join(r[0][0].split()) for r in readings]
    if any(not quoted(v) for v in values) or norm(values[0])!=norm(values[1]):
        return None
    if any(not .55<=r[0][1]<=1 for r in readings):
        return None
    prefix=values[0].split('«',1)[0].strip()
    if not norm(before).startswith(norm(prefix)):
        return None
    return values[0]


def recover(pages,analysis,fields,evidence,gpu=True):
    import numpy as np
    import cv2
    from dekanat.ocr import quote_state,get_reader
    started=time.perf_counter();attempts=[];changes=[]
    weights=quote_state()
    if weights is None:return {'attempts':[],'changes':[],'reason':'no_selected_quote_weights','seconds':0}
    for key in ['university','organization']:
        before=fields.get(key,MISSING)
        if before==MISSING or quoted(before) or evidence.get(key,{}).get('status')=='conflict':continue
        lines=[l for l in analysis.get('ocr',{}).get('lines',[]) if re.match(r'^\s*'+re.escape(LABELS[key])+r'\s*:',l['text'],re.I)]
        if len(lines)!=1:continue
        line=lines[0];page=pages[line['page']]
        x1,y1,x2,y2=map(int,line['bbox'])
        x1=max(0,x1-5);y1=max(0,y1-5);x2=min(page.width,x2+20);y2=min(page.height,y2+5)
        if x2<=x1 or y2<=y1 or y2-y1>160:continue
        gray=cv2.cvtColor(np.asarray(page)[y1:y2,x1:x2],cv2.COLOR_RGB2GRAY)
        cuts=colon_cuts(gray)
        if len(cuts)!=1:continue
        crop=gray[:,cuts[0]+1:]
        reader=get_reader(gpu,weights,detector=False)
        readings=[]
        for scale in [1,2]:
            image=cv2.resize(crop,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC) if scale==2 else crop
            readings.append([[str(p[1]),float(p[2])] for p in reader.recognize(image,detail=1,decoder='greedy',batch_size=1)])
        value=accepted_value(before,readings)
        attempt={'key':key,'before':before,'page':line['page'],'bbox':[x1+cuts[0]+1,y1,x2,y2],
            'colon_cut':cuts[0],'readings':readings,'accepted':value,'variants':['gray_native','gray_cubic_2x']}
        attempts.append(attempt)
        if value is not None:
            fields[key]=value
            evidence[key]={'status':'uncertain','source':'bounded_value_quote_reread','semantic_confidence':None,
                'source_confidence':min(r[0][1] for r in readings),'previous':evidence.get(key),'reread':attempt,'value':value}
            changes.append(key)
    return {'attempts':attempts,'changes':changes,'seconds':time.perf_counter()-started}
