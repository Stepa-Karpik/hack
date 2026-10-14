"""Source-bound patterns for institutional forms; no institution/name lookup."""
import re
from datetime import datetime
from .narrative import NAME,DATE,NUMBER_SIGN,windows

MONTHS={name:i+1 for i,name in enumerate(['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'])}
TEXT_DATE=r'(?:'+DATE+r'|\d{1,2}\s+(?:'+'|'.join(MONTHS)+r')\s+\d{4})(?:\s*г[.]?)?'
LEAVE_BEFORE_PERIOD=r'\bпрошу\s+предоставить\s+(?:мне\s+)?академический\s+отпуск\s+(?P<category>по\s+(?:семейным\s+обстоятельствам|медицинским\s+показаниям))\s+(?:[сc]\s+)?(?P<start>'+TEXT_DATE+r')\s+(?:по|до)\s+(?P<end>'+TEXT_DATE+r')\s+в\s+связи\s+[сc]\s+(?P<cause>[^.\n]{3,150})(?:[.]|$)'


def date_value(text):
    text=re.sub(r'\s*г[.]?\s*$','',text.strip(),flags=re.IGNORECASE)
    try:
        if re.fullmatch(DATE,text):return datetime.strptime(text,'%d.%m.%Y').strftime('%d.%m.%Y')
        m=re.fullmatch(r'(\d{1,2})\s+([а-я]+)\s+(\d{4})',text,re.IGNORECASE)
        if m and m[2].lower() in MONTHS:return datetime(int(m[3]),MONTHS[m[2].lower()],int(m[1])).strftime('%d.%m.%Y')
    except ValueError:pass
    return None


def candidates(rows,kind):
    result=[];seen=set()
    def emit(key,value,parts,rule):
        value=re.sub(r'\s+',' ',value).strip()
        if not value:return
        identity=(key,value,tuple((p['page'],tuple(p['bbox'])) for p in parts))
        if identity in seen:return
        seen.add(identity)
        text='\n'.join(p['text'] for p in parts)
        result.append({'key':key,'value':value,'evidence':{'method':'institutional_pattern','rule':rule,
                      'text':text,'source_text':text,'parts':[dict(p) for p in parts],'page':parts[0]['page'],
                      'confidence':min(p['confidence'] for p in parts),
                      'bbox':[min(p['bbox'][0] for p in parts),min(p['bbox'][1] for p in parts),max(p['bbox'][2] for p in parts),max(p['bbox'][3] for p in parts)]}})
    def nearby(a,b,max_gap=2,min_gap=0,min_overlap=.3):
        height=max(a['bbox'][3]-a['bbox'][1],b['bbox'][3]-b['bbox'][1])
        gap=b['bbox'][1]-a['bbox'][3]
        overlap=min(a['bbox'][2],b['bbox'][2])-max(a['bbox'][0],b['bbox'][0])
        width=min(a['bbox'][2]-a['bbox'][0],b['bbox'][2]-b['bbox'][0])
        return a['page']==b['page'] and min_gap*height<=gap<max_gap*height and overlap>=min_overlap*width
    for parts in windows(rows,relaxed=True):
        text='\n'.join(p['text'] for p in parts)
        if kind=='leave':
            for m in re.finditer(LEAVE_BEFORE_PERIOD,text,re.IGNORECASE):
                start,end=date_value(m['start']),date_value(m['end'])
                if start and end:
                    emit('start_date',start,parts,'leave_reason_before_period')
                    emit('end_date',end,parts,'leave_reason_before_period')
                    emit('reason',m['category']+' в связи с '+m['cause'],parts,'leave_reason_before_period')
        if kind=='practice':
            # Both boundaries and the semantic role must be printed; no repair of names or grades.
            for m in re.finditer(r'\bпрактику\s+в\s+((?:ООО|АО|ЗАО|ОАО)\s+[«»"]([^«»"\n]{3,120})[«»"])(?=[.,;\s]|$)',text):
                legal=m[1].split()[0]
                emit('organization',legal+' «'+m[2]+'»',parts,'explicit_quoted_practice_organization')
            for m in re.finditer(r'\bзаслуживает\s+оценки\s+[«»"](отлично|хорошо|неудовлетворительно|удовлетворительно|незачтено|зачтено)[«»"]',text,re.IGNORECASE):
                emit('grade',m[1],parts,'explicit_narrative_practice_grade')
            for m in re.finditer(r'\bв\s+период\s+('+TEXT_DATE+r')\s+по\s+('+TEXT_DATE+r')\s+проходил',text,re.IGNORECASE):
                start,end=date_value(m[1]),date_value(m[2])
                if start and end:emit('practice_period',start+' - '+end,parts,'explicit_practice_period_before_verb')
            m=re.search(r'(?i:Руководитель\s+практики\s+(?:от|OT)\s+организации\s*\(предприятия\)\s+)('+NAME+r')(?=[,.;]|$)',text)
            if m:emit('supervisor',m[1],parts,'organization_supervisor_with_role')
        if kind=='study':
            for m in re.finditer(r'\b(очно-заочной|очной|заочной)\s+формы\s+обучения',text,re.IGNORECASE):
                emit('study_form',{'очной':'очная','заочной':'заочная','очно-заочной':'очно-заочная'}[m[1].lower()],parts,'explicit_study_form_phrase')
    for row in rows:
        if kind=='leave':
            if re.fullmatch(r'[1-9]',row['text']):
                height=row['bbox'][3]-row['bbox'][1]
                aligned=lambda p:p['page']==row['page'] and abs((p['bbox'][1]+p['bbox'][3]-row['bbox'][1]-row['bbox'][3])/2)<.5*max(height,p['bbox'][3]-p['bbox'][1])
                left=[p for p in rows if aligned(p) and re.fullmatch(r'от\s+студент(?:а|ки)(?:\(тки\))?',p['text'],re.IGNORECASE) and 0<=row['bbox'][0]-p['bbox'][2]<5*height]
                right=[p for p in rows if aligned(p) and re.fullmatch('курса',p['text'],re.IGNORECASE) and 0<=p['bbox'][0]-row['bbox'][2]<5*height]
                if len(left)==len(right)==1:emit('course',row['text'],[left[0],row,right[0]],'course_between_student_and_course_labels')
            m=re.fullmatch(r'(?i:Прошу\s+предоставить\s+(?:мне\s+)?академический\s+отпуск\s+)(?P<category>по\s+семейным\s+обстоятельствам)\s*[.]?',row['text'],re.IGNORECASE)
            if m:
                dated=[p for p in rows if nearby(row,p,2.5,min_gap=-.35) and re.search(DATE,p['text'])]
                if not dated:emit('reason',m['category'],[row],'explicit_reason_in_unfilled_request')
            if re.fullmatch(NAME,row['text']):
                captions=[p for p in rows if nearby(row,p,1.5) and re.search(r'фамилия\s*[,;.]\s*имя',p['text'],re.IGNORECASE)]
                student_context=[p for p in rows if p['page']==row['page'] and re.search(r'\bот\s+студент(?:а|ки)',p['text'],re.IGNORECASE)
                                 and 0<=row['bbox'][1]-p['bbox'][3]<14*(row['bbox'][3]-row['bbox'][1])]
                if len(captions)==1 and student_context:emit('student_name',row['text'],[student_context[-1],row,captions[0]],'applicant_name_above_caption')
            m=re.search(r'\bот\s+студент[^\d]{0,15}\s+(\d{1,2})(\s+курса)?\s*$',row['text'],re.IGNORECASE)
            if m:
                if m[2]:emit('course',m[1],[row],'course_in_applicant_header')
                height=row['bbox'][3]-row['bbox'][1]
                labels=[p for p in rows if p['page']==row['page'] and re.fullmatch('курса',p['text'],re.IGNORECASE)
                        and 0<=p['bbox'][0]-row['bbox'][2]<4*height and abs((p['bbox'][1]+p['bbox'][3]-row['bbox'][1]-row['bbox'][3])/2)<.5*height]
                if len(labels)==1:emit('course',m[1],[row,labels[0]],'course_in_split_applicant_header')
        if kind in {'study','practice'}:
            m=re.fullmatch(r'('+DATE+r')\s*'+NUMBER_SIGN+r'\s*',row['text'])
            if m and date_value(m[1]):emit('issue_date',date_value(m[1]),[row],'date_with_empty_registration_number')
        if kind=='study':
            named=re.search(r'\bВыдана\s+([А-ЯЁ][а-яё]+)\s*$',row['text'])
            if named:
                seconds=[p for p in rows if nearby(row,p,1.5) and re.fullmatch(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+',p['text'])]
                if len(seconds)==1:emit('student_name',named[1]+' '+seconds[0]['text'],[row,seconds[0]],'split_recipient_after_issuance_label')
            m=re.fullmatch(r'([А-ЯЁ]{2,12}\s+имени\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][.]?\s*[А-ЯЁ][.]?)\s+очной\s+формы\s+обучения',row['text'])
            if m:emit('university',m[1],[row],'abbreviated_institution_before_study_form')
            if re.fullmatch(r'\d{2}\.\d{2}\.\d{2}\s+\S.{2,100}',row['text']):
                anchors=[p for p in rows if nearby(p,row,3) and re.search(r'является\s+студентом\s+направления',p['text'],re.IGNORECASE)]
                if anchors:emit('program',row['text'],[anchors[-1],row],'program_below_explicit_direction')
            m=re.fullmatch(r'[А-ЯЁ][а-яё]+',row['text'])
            if m:
                seconds=[p for p in rows if nearby(row,p,1.5) and re.fullmatch(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+',p['text'])]
                height=row['bbox'][3]-row['bbox'][1]
                labels=[p for p in rows if p['page']==row['page'] and re.search(r'\bВыдана\s*$',p['text'])
                        and 0<=row['bbox'][0]-p['bbox'][2]<6*height and abs((p['bbox'][1]+p['bbox'][3]-row['bbox'][1]-row['bbox'][3])/2)<height]
                if len(seconds)==1 and labels:emit('student_name',row['text']+' '+seconds[0]['text'],[labels[-1],row,seconds[0]],'split_certificate_recipient')
        if kind=='practice' and re.fullmatch(DATE,row['text']):
            stamps=[p for p in rows if nearby(p,row,2,min_overlap=.25) and re.fullmatch(r'м[.\s]*п[.:]?',p['text'],re.IGNORECASE)]
            if len(stamps)==1 and date_value(row['text']):emit('issue_date',date_value(row['text']),[stamps[0],row],'date_under_stamp_placeholder')
    return result
