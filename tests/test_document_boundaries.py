import pytest
from dekanat.extraction import detect_type
from dekanat.field_validation import validate_fields


def row(text,y=0,page=0):return {'text':text,'bbox':[100,y,800,y+30],'page':page,'confidence':.9}


def test_two_certificate_titles_on_same_page_rejected():
    assert detect_type([row('СПРАВКА'),row('СПРАВКА',y=500),row('обучение',y=550)]) is None


def test_titles_on_separate_pages_allow_one_multipage_document():
    assert detect_type([row('СПРАВКА'),row('СПРАВКА',y=500,page=1),row('обучение',y=550,page=1)])=='study'


def test_near_duplicate_ocr_title_not_a_second_document():
    assert detect_type([row('СПРАВКА'),row('СПРАВКА',y=25),row('обучение',y=100)])=='study'


@pytest.mark.parametrize('verb',['пишется','составляется','оформляется'])
def test_instructions_to_write_practice_review_are_unsupported(verb):
    assert detect_type([row('Отзыв '+verb+' на фирменном бланке'),row('Продолжительность практики',y=100)]) is None


def test_actual_practice_review_stays_supported():
    assert detect_type([row('ОТЗЫВ о прохождении практики'),row('Студент проходил практику',y=100)])=='practice'


@pytest.mark.parametrize('verb',['выдать','выслать','оформить','подготовить'])
def test_request_for_a_certificate_not_a_certificate_or_leave(verb):
    assert detect_type([row('ЗАЯВЛЕНИЕ'),row('Прошу '+verb+' справку об обучении',y=100),row('Забрать академическую справку лично',y=200)]) is None


def test_issued_certificate_not_rejected_as_a_request():
    assert detect_type([row('СПРАВКА'),row('Выдана студенту, обучение продолжается',y=100)])=='study'


def test_academic_leave_not_confused_with_academic_certificate():
    assert detect_type([row('Прошу предоставить академический отпуск',y=100)])=='leave'
    assert detect_type([row('Академическая справка об обучении')])=='study'


@pytest.mark.parametrize('value',['полноспью','Иванов','И.И.','Иванов 3','Смит-Джонс',"O'Connell",'Nicólás','Иванов/Петров'])
def test_incomplete_name_retained_but_not_confirmed(value):
    f={'value':value,'status':'found','confidence':.9,'evidence':row('ФИО '+value)}
    validate_fields({'student_name':f})
    assert f['status']=='uncertain' and f['value']==value and f['confidence']==.9


@pytest.mark.parametrize('value',['Иванов Павел Сергеевич','Иванов Павел','Иванов И.И.','Smith John','Смит-Джонс Алексей','Nicólás Ramírez',"John O'Connell",'Nico\u0301las Ramirez'])
def test_complete_printed_name_or_surname_with_initials_preserved(value):
    f={'value':value,'status':'found','confidence':.9,'evidence':row('ФИО '+value)}
    validate_fields({'student_name':f});assert f['status']=='found'


def test_name_validation_does_not_promote_uncertainty_or_override_conflict():
    for status in ['uncertain','conflict']:
        f={'value':'Иванов','status':status,'confidence':.9,'evidence':row('ФИО Иванов')}
        validate_fields({'student_name':f});assert f['status']==status


@pytest.mark.parametrize('value',['обучающегося полностью )','заявителя полностью','ФИО студента','расшифровка подпись','Иванов Иван Иванович (полностью)'])
def test_instruction_suffixes_not_confirmed_as_names(value):
    f={'value':value,'status':'found','confidence':.99,'evidence':row('ФИО '+value)}
    validate_fields({'student_name':f});assert f['status']=='uncertain' and f['value']==value


@pytest.mark.parametrize('adjective',['академический','академичсский','академического'])
def test_academic_leave_object_survives_suffix_ocr_error(adjective):
    assert detect_type([row('Прошу предоставить мне '+adjective+' отпуск')])=='leave'


def test_return_from_leave_not_request_to_grant_leave():
    assert detect_type([row('Прошу считать меня вышедшим из академического отпуска. Справку прилагаю.')]) is None
    assert detect_type([row('Прошу предоставить академический отпуск'),row('С правилами выхода из академического отпуска ознакомлена',y=100)])=='leave'
    assert detect_type([row('Академическая задолженность')]) is None


@pytest.mark.parametrize('value',['БЕЗ ПОДПИСИ:','Учебный пример','Не является документом'])
def test_bare_disclaimer_not_confirmed_as_organization(value):
    f={'value':value,'status':'found','confidence':.99,'evidence':row(value)}
    validate_fields({'organization':f});assert f['status']=='uncertain' and f['value']==value


def test_legal_entity_name_containing_disclaimer_words_preserved():
    f={'value':'ООО «Без подписи»','status':'found','confidence':.99,'evidence':row('Организация ООО «Без подписи»')}
    validate_fields({'organization':f});assert f['status']=='found'


def test_corrupted_type_cue_requires_review_without_correcting_ocr_text():
    from dekanat.extraction import type_review_reason
    lines=[row('Прошу предоставить академичсский отпуск')]
    assert type_review_reason(lines,detect_type(lines))
    assert lines[0]['text']=='Прошу предоставить академичсский отпуск'
    assert type_review_reason([row('Прошу предоставить академический отпуск')],'leave') is None
    assert type_review_reason([row('Причина отпуска')],'leave') is None


def test_type_review_preserves_values_confidence_and_existing_uncertainty():
    from dekanat.field_validation import require_type_review
    fields={s:{'value':'Иванов Иван','status':s,'confidence':.9} for s in ['found','uncertain','conflict','not_found']}
    assert len(require_type_review(fields,'Проверьте тип'))==1
    assert fields['found']['status']=='uncertain'
    assert all(f['value']=='Иванов Иван' and f['confidence']==.9 for f in fields.values())
    assert fields['conflict']['status']=='conflict'
    assert not require_type_review(fields,None)
