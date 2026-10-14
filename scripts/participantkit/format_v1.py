"""Organizer contract adapter. Never reads document labels/reference answers."""
import re
from datetime import date

KINDS={'study_certificate':'study','academic_leave_application':'leave','internship_certificate':'practice'}
MISSING='не найдено'
LABELS={'student_name':'ФИО студента','university':'Название вуза','program':'Направление подготовки',
    'study_form':'Форма обучения','study_start':'Начало периода обучения','study_end':'Окончание периода обучения',
    'document_number':'Номер справки','issue_date':'Дата выдачи','group':'Учебная группа','course':'Курс',
    'leave_reason':'Причина отпуска','leave_start':'Дата начала отпуска','leave_end':'Дата окончания отпуска',
    'application_date':'Дата заявления','organization':'Название организации','internship_start':'Дата начала практики',
    'internship_end':'Дата окончания практики','supervisor_name':'ФИО руководителя практики','grade':'Оценка',
    'signature_present':'Подпись','seal_present':'Печать'}
MONTHS={m:i+1 for i,m in enumerate(['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'])}
DATE=r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{1,2}\s+(?:'+ '|'.join(MONTHS)+r')\s+\d{4}(?:\s+года)?)'

def norm(value):return re.sub(r'\s+',' ',value.casefold().replace('ё','е')).strip(' .:«»"')

def iso(value):
    if not isinstance(value,str):return MISSING
    text=value.casefold().strip()
    match=re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',text)
    if match:y,m,d=map(int,match.groups())
    else:
        match=re.fullmatch(r'(\d{1,2})[./-](\d{1,2})[./-](\d{4})',text)
        if match:d,m,y=map(int,match.groups())
        else:
            match=re.fullmatch(r'(\d{1,2})\s+('+ '|'.join(MONTHS)+r')\s+(\d{4})(?:\s+года)?',text)
            if not match:return MISSING
            d,y=int(match[1]),int(match[3]);m=MONTHS[match[2]]
    try:return date(y,m,d).isoformat()
    except ValueError:return MISSING

def fields_from_v21(analysis,document_type,config):
    raw=analysis['fields']
    def value(key):
        f=raw.get(key,{})
        return f.get('value') if f.get('status')!='conflict' else None
    mapping={'leave_reason':'reason','leave_start':'start_date','leave_end':'end_date','supervisor_name':'supervisor'}
    output={}
    for key in [k for group in config['requirements'][document_type].values() for k in group]:
        if key in {'signature_present','seal_present'}:
            # Literal visual prediction retained; uncertainty remains in raw diagnostic/UI.
            output[key]=value('signature' if key=='signature_present' else 'stamp') is True
        elif key in {'study_start','study_end','internship_start','internship_end'}:
            period=value('study_period' if key.startswith('study_') else 'practice_period')
            dates=re.findall(DATE,str(period or ''),re.IGNORECASE)
            output[key]=iso(dates[0 if key.endswith('start') else 1]) if len(dates)==2 else MISSING
        else:
            v=value(mapping.get(key,key))
            output[key]=iso(v) if key in {'leave_start','leave_end','issue_date','application_date'} else str(v).strip() if v is not None and str(v).strip() else MISSING
    return output

def validate(fields,document_type,config):
    missing=[k for k,v in fields.items() if v is False or v==MISSING]
    requirements=config['requirements'][document_type]
    sources=['rule:'+rid for rid,keys in requirements.items() if not missing or any(k in missing for k in keys)]
    return {'status':'missing_fields' if missing else 'document_ok','missing_fields':missing,'sources':sources}

def answer(question,fields,validation,config):
    q=norm(question)
    no={'answerable':False,'value':None,'answer':'В документе и в Положении нет информации для ответа на этот вопрос. Обратитесь в деканат.','sources':[]}
    if ('обязательн' in q and ('содержит' in q or 'все' in q)) or 'комплектност' in q:
        text='Не найдены обязательные сведения: '+', '.join(LABELS[k] for k in validation['missing_fields'])+'.' if validation['missing_fields'] else 'Документ содержит все обязательные сведения.'
        return {'answerable':True,'value':validation['status'],'answer':text+' Основание: '+', '.join(validation['sources'])+'. Окончательное решение примет сотрудник деканата.','sources':validation['sources']}
    if 'кто' in q and 'окончательн' in q and 'решени' in q and '1.3' in config['rules']:
        return {'answerable':True,'value':'сотрудник деканата','answer':config['rules']['1.3'],'sources':['rule:1.3']}
    matches=[k for k in fields if norm(LABELS[k]) in q]
    if len(matches)==1:
        key=matches[0];v=fields[key]
        if v==MISSING:return no
        text=str(v).lower() if isinstance(v,bool) else v
        return {'answerable':True,'value':text,'answer':LABELS[key]+': '+text+'.','sources':['field:'+key]}
    return no
