import pytest
from dekanat.slots import fill_missing_slots
from dekanat.field_validation import validate_fields

def row(text,y=0,x=100,page=0,confidence=.9):
    return {'text':text,'bbox':[x,y,x+350,y+20],'page':page,'confidence':confidence}

def empty():return {'value':None,'status':'not_found','confidence':0,'evidence':None}

@pytest.mark.parametrize('name',['ЛЕБЕДЕВ СЕМЁН ВИКТОРОВИЧ','Алиева-Орлова Тамара Рустамовна'])
def test_name_bound_to_student_context_and_caption(name):
    fields={'student_name':empty()}
    fill_missing_slots([row('от студента'),row(name,40),row('(Ф.И.О.)',70)],fields,'leave')
    assert fields['student_name']['value']==name and fields['student_name']['status']=='found'

@pytest.mark.parametrize('case',['other_column','other_page','no_student_context','distant_caption'])
def test_name_not_borrowed_from_unrelated_caption(case):
    lines=[row('от студента'),row('СИДОРОВ ИГОРЬ МИХАЙЛОВИЧ',40),row('(Ф.И.О.)',70)]
    if case=='other_column':lines[-1]=row('(Ф.И.О.)',70,x=700)
    if case=='other_page':lines[-1]['page']=1
    if case=='no_student_context':lines=lines[1:]
    if case=='distant_caption':lines[-1]=row('(Ф.И.О.)',400)
    fields={'student_name':empty()};fill_missing_slots(lines,fields,'leave')
    assert fields['student_name']['value'] is None

@pytest.mark.parametrize('status',['found','uncertain','conflict'])
def test_existing_value_and_status_preserved(status):
    old={'value':'Ф-12','status':status,'confidence':.8,'evidence':row('Old')}
    fields={'group':old};fill_missing_slots([row('Группы № Ф-31')],fields,'leave')
    assert fields['group'] is old

def test_conflict_without_value_not_promoted():
    f=empty();f['status']='conflict';fields={'group':f}
    fill_missing_slots([row('Группы № Ф-31')],fields,'leave');assert fields['group'] is f

def test_two_different_group_candidates_not_selected_arbitrarily():
    fields={'group':empty()};fill_missing_slots([row('Группы № Ф-31'),row('Группы № Ф-42',50)],fields,'leave')
    assert fields['group']['value'] is None

def test_low_source_confidence_retained_for_review():
    fields={'group':empty()};fill_missing_slots([row('Группы № Ф-31',confidence=.4)],fields,'leave')
    assert fields['group']['value']=='Ф-31' and fields['group']['status']=='uncertain' and fields['group']['confidence']==.4

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,2])
def test_invalid_source_confidence_not_used(value):
    fields={'group':empty()};fill_missing_slots([row('Группы № Ф-31',confidence=value)],fields,'leave')
    assert fields['group']['value'] is None

def test_date_requires_request_and_signature_not_birth_date():
    fields={'application_date':empty()}
    fill_missing_slots([row('Дата: 12.10.2026'),row('Подпись.',30)],fields,'leave')
    assert fields['application_date']['value'] is None
    lines=[row('Прошу предоставить академический отпуск'),row('Дата рождения: 12.10.2005',200),row('Подпись.',220)]
    fill_missing_slots(lines,fields,'leave');assert fields['application_date']['value'] is None

def test_invalid_calendar_date_still_reviewed_after_slot_recovery():
    fields={'application_date':empty()}
    lines=[row('Прошу предоставить академический отпуск'),row('Дата: 31.02.2026',200),row('Подпись.',220)]
    fill_missing_slots(lines,fields,'leave');validate_fields(fields)
    assert fields['application_date']['value']=='31.02.2026' and fields['application_date']['status']=='uncertain'

def test_scientific_supervisor_needs_role_and_same_column():
    fields={'supervisor':empty()}
    fill_missing_slots([row('доцент Липатова Инна Борисовна',50)],fields,'practice');assert fields['supervisor']['value'] is None
    fill_missing_slots([row('Научный руководитель,'),row('доцент Липатова Инна Борисовна',30)],fields,'practice')
    assert fields['supervisor']['value']=='Липатова Инна Борисовна'


def test_faculty_header_before_group_not_borrowed_as_student_name():
    fields={'student_name':empty()}
    lines=[row('от студента'),row('ФИЗИЧЕСКОГО ФАКУЛЬТЕТА УНИВЕРСИТЕТА',40),row('Группы № ______',68),row('(Ф.И.О.)',94)]
    fill_missing_slots(lines,fields,'leave');assert fields['student_name']['value'] is None


def test_application_date_not_borrowed_from_staff_without_student_request():
    fields={'application_date':empty()}
    lines=[row('Академический руководитель'),row('Дата: 12.10.2026',200),row('Подпись.',220)]
    fill_missing_slots(lines,fields,'leave');assert fields['application_date']['value'] is None


@pytest.mark.parametrize('role',['Академический руководитель','Декан факультета','Ректор университета'])
def test_staff_approval_date_not_student_application_date(role):
    fields={'application_date':empty()}
    lines=[row('Прошу предоставить академический отпуск'),row(role,100),row('Дата: 12.10.2026',200),row('Подпись.',220)]
    fill_missing_slots(lines,fields,'leave');assert fields['application_date']['value'] is None
