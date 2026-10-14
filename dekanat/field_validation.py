"""Evidence-preserving date normalization and ambiguous program-code review."""
from datetime import date
import re
import unicodedata

DATE_FIELDS = {'issue_date', 'start_date', 'end_date', 'application_date'}
PERIOD_FIELDS = {'study_period', 'practice_period'}
NUMERIC_DATE = r'(?:[0-9]{1,2}\s*[.,/]\s*[0-9]{1,2}\s*[.,/]\s*[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})'


def require_type_review(fields,reason):
    changes=[]
    if reason:
        for key,field in fields.items():
            if field['status']=='found':
                field['status']='uncertain'
                field.setdefault('validation',[]).append({'rule':'weak_auto_type_cue','reason':reason})
                changes.append({'field':key,'action':'review_required','reason':reason})
    return changes


def parse_numeric_date(value):
    match = re.fullmatch(r'([0-9]{1,2})\s*[.,/]\s*([0-9]{1,2})\s*[.,/]\s*([0-9]{4})', value.strip())
    if match:
        day, month, year = map(int, match.groups())
    else:
        match = re.fullmatch(r'([0-9]{4})-([0-9]{2})-([0-9]{2})', value.strip())
        if not match:
            return None
        year, month, day = map(int, match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def validate_fields(fields):
    """Never promote uncertainty/conflicts or infer missing date digits.

    Unsupported formats are kept for review; this is not a policy requirement
    that all documents use numeric dates or proof that recognized digits match.
    """
    changes = []
    for key, field in fields.items():
        if key=='organization' and isinstance(field.get('value'),str) and field['status']=='found':
            bare=field['value'].casefold().strip(' .:;!')
            if bare in {'без подписи','учебный пример','не является документом'}:
                reason='Прочитано служебное примечание, а не название организации; проверьте источник.'
                field['status']='uncertain'
                field.setdefault('validation',[]).append({'rule':'organization_disclaimer','raw_value':field['value'],'reason':reason})
                changes.append({'field':key,'action':'review_required','reason':reason})
        if key=='student_name' and isinstance(field.get('value'),str) and field['status']=='found':
            normalized_name=unicodedata.normalize('NFC',field['value'])
            tokens=re.findall(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*",normalized_name)
            instruction=re.search(r'\b(?:полностью|обучающегося|обучающейся|заявителя|студента|расшифровка|подпись)\b',normalized_name,re.IGNORECASE)
            if len(tokens)<2 or not any(len(t)>1 for t in tokens) or re.search(r'[\d/]',field['value']) or instruction:
                reason='ФИО прочитано не полностью либо содержит неоднозначные символы; сверьте имя с изображением.'
                field['status']='uncertain'
                field.setdefault('validation',[]).append({'rule':'incomplete_student_name','raw_value':field['value'],'reason':reason})
                changes.append({'field':key,'action':'review_required','reason':reason})
        if key == 'program' and isinstance(field.get('value'), str):
            token = field['value'].split()[0] if field['value'].split() else ''
            if (re.fullmatch(r'[0-9OoОо]{2}\.[0-9OoОо]{2}\.[0-9OoОо]{2}', token)
                    and re.search(r'[0-9]', token) and re.search(r'[OoОо]', token)
                    and field['status'] == 'found'):
                reason = 'В похожем на числовой код направления есть неоднозначная буква O/О; сверьте код с изображением.'
                field['status'] = 'uncertain'
                field.setdefault('validation', []).append({'rule':'ambiguous_program_code', 'raw_value':field['value'], 'reason':reason})
                changes.append({'field':key,'action':'review_required','reason':reason})
        if key not in DATE_FIELDS | PERIOD_FIELDS or not isinstance(field.get('value'), str):
            continue
        raw = field['value']
        normalized, reason = None, None
        if key in DATE_FIELDS:
            parsed = parse_numeric_date(raw)
            if parsed:
                normalized = parsed.strftime('%d.%m.%Y')
            else:
                reason = 'Дата не распознана в поддерживаемом полном числовом формате или не существует в календаре; проверьте источник.'
        else:
            match = re.fullmatch(r'\s*(?:с\s+)?('+NUMERIC_DATE+r')(?:\s*(?:[-–—]|по|до)\s*|\s+)('+NUMERIC_DATE+r')\s*', raw, flags=re.IGNORECASE)
            first, last = (parse_numeric_date(v) for v in match.groups()) if match else (None, None)
            if first and last and first <= last:
                normalized = first.strftime('%d.%m.%Y')+' - '+last.strftime('%d.%m.%Y')
            else:
                reason = 'Период не распознан как две полные календарные даты в порядке начала и окончания; проверьте источник.'
        if normalized is not None and normalized != raw:
            field['value'] = normalized
            field.setdefault('validation', []).append({'rule':'numeric_date_punctuation', 'raw_value':raw,
                                                      'normalized_value':normalized, 'scope':'Only explicit day/month/year digits and separators; no date inference'})
            changes.append({'field':key,'action':'normalized','raw_value':raw,'value':normalized})
        if reason and field['status'] == 'found':
            field['status'] = 'uncertain'
            field.setdefault('validation', []).append({'rule':'date_structure_review','raw_value':raw,'reason':reason})
            changes.append({'field':key,'action':'review_required','reason':reason})
    return {'changes':changes, 'scope':'Numeric date syntax/calendar, incomplete name structure and letter O in a numeric-looking program code; no missing letters/digits inferred, correctness not guaranteed'}
