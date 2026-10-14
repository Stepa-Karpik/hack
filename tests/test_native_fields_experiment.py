"""Isolated prototype checks; importing here does not enable the app route."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from native_fields_candidate import canonical, extract_candidate, shifted_signature_date
from probe_native_missing_replay import enrich

def row(text, y, x=100, page=0):
    return {'text':text,'bbox':[x,y,x+100,y+20],'page':page,'confidence':.9}

def empty():
    return {'application_date':{'value':None,'status':'not_found','confidence':0,'evidence':None}}

def lines():
    return [row('Прошу предоставить мне академический отпуск',0),
            row('(подпись)',80),row('10.10.2026',110,210)]

def test_shifted_date_literal_and_parts():
    fields=empty();assert shifted_signature_date(lines(),fields,'leave')
    assert fields['application_date']['value']=='10.10.2026'
    assert len(fields['application_date']['evidence']['parts'])==3

@pytest.mark.parametrize('case',['wrong_page','far_x','far_y','invalid_calendar','staff','two_dates','no_request'])
def test_date_negative(case):
    rows=lines()
    if case=='wrong_page': rows[-1]['page']=1
    if case=='far_x': rows[-1]=row('10.10.2026',110,500)
    if case=='far_y': rows[-1]=row('10.10.2026',200,210)
    if case=='invalid_calendar': rows[-1]['text']='31.02.2026'
    if case=='staff': rows.append(row('Декан факультета',40))
    if case=='two_dates': rows.append(row('11.10.2026',115,215))
    if case=='no_request': rows=rows[1:]
    fields=empty();assert not shifted_signature_date(rows,fields,'leave')
    assert fields['application_date']['value'] is None

@pytest.mark.parametrize('status',['found','uncertain','conflict'])
def test_existing_dates_preserved(status):
    fields={'application_date':{'value':'12.10.2026','status':status}}
    previous=fields['application_date'];assert not shifted_signature_date(lines(),fields,'leave')
    assert fields['application_date'] is previous

def test_role_name_before_candidate_merge():
    text='от организации (предприятия) Гордеев Николай Алексеевич, руководитель отдела'
    assert canonical('supervisor',text)=='Гордеев Николай Алексеевич'
    # Unknown job/text stays intact; two people must not be collapsed.
    assert canonical('supervisor',text+', Иванов Иван Иванович')==text+', Иванов Иван Иванович'

def test_blank_supervisor_keeps_evidence_for_review():
    fields,_=extract_candidate([row('Руководитель практики',0),
                row('от организации (предприятия)_____',25)],'practice',
                Path(__file__).resolve().parents[1]/'models/fields.joblib')
    field=fields['supervisor']
    assert field['status']!='found' and field['evidence']
    assert field['value'].endswith('_____')

@pytest.mark.parametrize('status,value',[('found','Ф-31'),('uncertain','Ф-31'),('conflict',None),('not_found','Ф-31')])
def test_native_replay_preserves_nonempty_and_conflicts(status,value):
    old={'group':{'value':value,'status':status,'confidence':.8,'evidence':{'text':'old'}}}
    native={'group':{'value':'Ф-32','status':'found','confidence':1,'evidence':{'text':'native'}}}
    after,changes=enrich(old,native)
    assert not changes and after==old

def test_native_replay_missing_literal_without_mutating_inputs():
    old={'group':{'value':None,'status':'not_found','confidence':0,'evidence':None}}
    native={'group':{'value':'Ф-32','status':'found','confidence':1,'evidence':{'text':'native'}}}
    after,changes=enrich(old,native)
    assert changes==['group'] and after['group']['value']=='Ф-32'
    assert old['group']['value'] is None and 'diagnostic_source' not in native['group']
