"""Full local pipeline experiment; production does not import this module."""
import copy,re,time
import cv2,numpy as np
from scripts.experiments.wrapped_names_guarded import select_rows,accept_proposal
from scripts.participantkit.crop_recovery import quoted
from scripts.participantkit.format_v1 import KINDS,MISSING,validate,answer,norm
from scripts.participantkit.service import prepare_result,load_config


def reread(pages,analysis,fields,bindings,gpu=True):
    before=fields.get('university',MISSING);raw=analysis.get('fields',{}).get('university',{})
    binding=bindings.get('university',{})
    if raw.get('status') in {'found','conflict'} or binding.get('status')=='conflict' or before==MISSING or quoted(before):
        return {'accepted':None,'reason':'preserve_found_conflict_missing_closed','attempted':False}
    lines=analysis.get('ocr',{}).get('lines',[]);parts,reason=select_rows(lines)
    if not parts:return {'accepted':None,'reason':reason,'attempted':False}
    page_index=parts[0].get('page',0)
    if not isinstance(page_index,int) or not 0<=page_index<len(pages):
        return {'accepted':None,'reason':'page_unavailable','attempted':False}
    from dekanat.ocr import get_reader,quote_state
    weights=quote_state()
    if weights is None:return {'accepted':None,'reason':'quote_weights_unavailable','attempted':False}
    reader=get_reader(gpu,weights,detector=False);page=pages[page_index];variants=[]
    for scale in [1,2]:
        readings=[]
        for part in parts:
            x1,y1,x2,y2=part['bbox']
            bounds=(max(0,int(x1)-8),max(0,int(y1)-6),min(page.width,int(x2)+12),min(page.height,int(y2)+6))
            if bounds[2]<=bounds[0] or bounds[3]<=bounds[1] or bounds[2]-bounds[0]>2000 or bounds[3]-bounds[1]>160:
                return {'accepted':None,'reason':'crop_budget','attempted':False}
            gray=cv2.cvtColor(np.asarray(page.crop(bounds)),cv2.COLOR_RGB2GRAY)
            if scale==2:gray=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
            items=reader.recognize(gray,detail=1,decoder='greedy',batch_size=1)
            readings.append([[str(p[1]),float(p[2])] for p in items])
        variants.append(readings)
    values=[]
    for readings in variants:
        if any(len(r)!=1 or not .5<=r[0][1]<=1 for r in readings):break
        text=' '.join(r[0][0] for r in readings)
        prefix=re.match(r'^\s*Название вуза\s*[:«]\s*',text,re.I)
        value=text[prefix.end():].strip() if prefix else None
        if value and quoted(value):values.append(value)
    candidate=values[0] if len(values)==2 and norm(values[0])==norm(values[1]) else None
    proposal={'parts':parts,'accepted':candidate,'readings':variants}
    accepted,reason=accept_proposal(before,raw,binding,proposal,lines)
    return {**proposal,'accepted':accepted,'reason':reason,'attempted':True,'semantic_confidence':None,
            'source_confidence':min((r[0][1] for variant in variants for r in variant if len(r)==1),default=0)}


def analyze_shadow(data,filename,document_type,questions,gpu=True,document_id='document'):
    from dekanat.pipeline import analyze
    pages,analysis=analyze(data,filename,document_type=KINDS[document_type],gpu=gpu)
    before,audit=prepare_result(pages,analysis,document_type,questions,document_id=document_id,gpu=gpu)
    started=time.perf_counter();proposal=reread(pages,analysis,before['fields'],audit['bindings'],gpu)
    after=copy.deepcopy(before);after_audit=copy.deepcopy(audit)
    if proposal['accepted']:
        after['fields']['university']=proposal['accepted']
        after_audit['bindings']['university']={'status':'uncertain','source':'shadow_wrapped_image',
            'semantic_confidence':None,'source_confidence':proposal['source_confidence'],
            'previous':audit['bindings'].get('university',{}),'reread':proposal}
        config=load_config();after['validation']=validate(after['fields'],document_type,config)
        after['answers']=[{'question_id':q['question_id'],**answer(q['question'],after['fields'],after['validation'],config)} for q in questions]
    return {'before':before,'after':after,'audit':after_audit,'proposal':proposal,'extra_seconds':time.perf_counter()-started}
