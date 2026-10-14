from pathlib import Path
import sys,json
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from format_v1 import iso,validate,answer,MISSING

@pytest.mark.parametrize('text,expected',[('01.09.2026','2026-09-01'),('2026-09-01','2026-09-01'),('1 сентября 2026 года','2026-09-01'),('31.02.2026',MISSING),('01.09.26',MISSING)])
def test_explicit_calendar_normalization(text,expected):assert iso(text)==expected

def config():return json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))

def fields():return {k:(True if k.endswith('_present') else 'literal') for ks in config()['requirements']['study_certificate'].values() for k in ks}

def test_full_document_uses_all_requirement_rules():
    v=validate(fields(),'study_certificate',config())
    assert v=={'status':'document_ok','missing_fields':[],'sources':['rule:3.1','rule:3.2','rule:3.3']}

def test_missing_sources_only_require_missing_elements():
    f=fields();f['issue_date']=MISSING;f['seal_present']=False
    v=validate(f,'study_certificate',config())
    assert v['missing_fields']==['issue_date','seal_present'] and v['sources']==['rule:3.1','rule:3.3']

def test_factual_missing_is_not_answerable_and_full_value_has_field_source():
    f=fields();f['issue_date']='2026-09-01';v=validate(f,'study_certificate',config())
    a=answer('Укажи значение поля «Дата выдачи».',f,v,config())
    assert a['value']=='2026-09-01' and a['sources']==['field:issue_date']
    f['issue_date']=MISSING;a=answer('Какова дата выдачи?',f,v,config())
    assert not a['answerable'] and a['value'] is None and a['sources']==[]

def test_decision_rule_and_unknown_question():
    f=fields();v=validate(f,'study_certificate',config())
    a=answer('Кто принимает окончательное решение о принятии документа?',f,v,config())
    assert a['value']=='сотрудник деканата' and a['sources']==['rule:1.3']
    a=answer('Какова стоимость обучения за следующий семестр?',f,v,config())
    assert not a['answerable'] and a['sources']==[]
