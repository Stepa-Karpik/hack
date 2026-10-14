"""Offline source-bound slot proposals. Not imported by deployed runtime."""
import re

WORD=r'[А-ЯЁа-яё]+(?:[-’\x27][А-ЯЁа-яё]+)*'
NAME=r'(?:'+WORD+r'\s+){2}'+WORD
DATE=r'\d{2}\.\d{2}\.\d{4}'

def propose(rows,kind):
    out=[]
    def emit(key,value,parts,rule):
        out.append({'key':key,'value':re.sub(r'\s+',' ',value).strip(),
                    'evidence':{'method':'offline_slot_prototype','rule':rule,'source_text':'\n'.join(p['text'] for p in parts),
                                'text':'\n'.join(p['text'] for p in parts),'page':parts[0]['page'],
                                'confidence':min(p['confidence'] for p in parts),'parts':parts,
                                'bbox':[min(p['bbox'][0] for p in parts),min(p['bbox'][1] for p in parts),max(p['bbox'][2] for p in parts),max(p['bbox'][3] for p in parts)]}})
    for row in rows:
        text=row['text'];h=row['bbox'][3]-row['bbox'][1]
        if kind=='leave':
            if re.fullmatch(NAME,text):
                captions=[p for p in rows if p['page']==row['page'] and re.fullmatch(r'\(?ф[.\s]*и[.\s]*о[.\s]*\)?',p['text'],re.IGNORECASE)
                          and 0<=p['bbox'][1]-row['bbox'][3]<2*h]
                context=[p for p in rows if p['page']==row['page'] and re.fullmatch(r'от\s+студента',p['text'],re.IGNORECASE)
                         and 0<=row['bbox'][1]-p['bbox'][3]<12*h]
                if len(captions)==1 and context:emit('student_name',text,[context[-1],row,captions[0]],'name_above_explicit_fio_caption')
            match=re.fullmatch(r'Групп[аы]\s*№?\s*([А-ЯЁа-яёA-Za-z0-9]+[-–][А-ЯЁа-яёA-Za-z0-9]+)',text,re.IGNORECASE)
            if match:emit('group',match[1],[row],'explicit_group_number')
            match=re.fullmatch(r'Прошу предоставить мне академический отпуск (по состоянию здоровья)[.]?',text,re.IGNORECASE)
            if match:emit('reason',match[1],[row],'explicit_single_medical_reason')
        if kind in {'leave','practice'}:
            match=re.fullmatch(r'Дата\s*[:：]\s*('+DATE+r')',text,re.IGNORECASE)
            anchors=[p for p in rows if p['page']==row['page'] and p['bbox'][3]<row['bbox'][1]
                     and re.search(r'Прошу предоставить|руководитель|оценивается на',p['text'],re.IGNORECASE)]
            signatures=[p for p in rows if p['page']==row['page'] and re.fullmatch(r'Подпись[.]?',p['text'],re.IGNORECASE)
                        and abs(p['bbox'][1]-row['bbox'][1])<2*h]
            if match and anchors and (kind=='practice' or signatures):
                emit('application_date' if kind=='leave' else 'issue_date',match[1],[anchors[-1],row],'explicit_date_after_request_or_assessment')
        if kind=='practice':
            match=re.fullmatch(r'(?i:Студента\(ки\)\s+\d{1,2}\s+курса\s+\S+\s+группы\s+)('+NAME+r')',text)
            if match:emit('student_name',match[1],[row],'practice_student_header')
            match=re.search(r'\bв период с ('+DATE+r') по ('+DATE+r') проходил',text,re.IGNORECASE)
            if match:emit('practice_period',match[1]+' - '+match[2],[row],'practice_period_before_explicit_verb')
            match=re.search(r'практики оценивается на (отлично|хорошо|удовлетворительно|неудовлетворительно)\s*[.]?$',text,re.IGNORECASE)
            if match:emit('grade',match[1],[row],'explicit_practice_assessment_sentence')
            match=re.fullmatch(r'(?i:доцент|профессор)\s+('+NAME+r')',text)
            if match:
                roles=[p for p in rows if p['page']==row['page'] and re.fullmatch(r'Научный руководитель[,]?',p['text'],re.IGNORECASE)
                       and 0<=row['bbox'][1]-p['bbox'][3]<2*h]
                if len(roles)==1:emit('supervisor',match[1],[roles[0],row],'scientific_supervisor_named_slot')
    return out
