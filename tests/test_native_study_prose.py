from scripts.unified.text_binding import bind
from scripts.unified.prose_binding import recover

TEXT = '''14.03.2032 № КР-41
Учебный город
СПРАВКА ОБ ОБУЧЕНИИ
Журавлев Егор Данилович является студентом второго курса
Института «Вымышленный университет долины».
Обучается по образовательной программе механики. Форма обучения: очная.
Период обучения: 01.09.2031 - 30.06.2035.
'''


def test_literal_prose_missing_only_offsets_and_no_mutation():
    original = bind(TEXT)
    result = recover(TEXT, original)
    assert result['fields']['student_name'] == 'Журавлев Егор Данилович'
    assert 'course' not in result['fields']
    assert result['fields']['study_start'] == '2031-09-01'
    assert result['fields']['study_end'] == '2035-06-30'
    assert result['fields']['study_form'] == 'очная'
    assert result['fields']['issue_date'] == '2032-03-14'
    assert result['fields']['document_number'] == 'КР-41'
    assert result['fields']['university'] == 'Вымышленный университет долины'
    assert result['fields']['program'] == 'механики'
    assert original['fields']['student_name'] is None
    audit = result['audit']['student_name']
    assert audit['semantic_confidence'] is None and audit['bbox'] is None
    span = audit['candidates'][0]['ocr_text_span']
    assert TEXT[slice(*span)] == 'Журавлев Егор Данилович'


def test_reject_staff_example_negation_wrong_type_and_truncation():
    for prefix in ['Образец:\n', 'Сотрудник отдела сообщил:\n', 'Не подтверждаем:\n']:
        text = TEXT.replace('Журавлев Егор', prefix+'Журавлев Егор')
        assert recover(text, bind(text)) == bind(text)
    assert recover(TEXT, bind(TEXT), truncated=True) == bind(TEXT)
    text=TEXT.replace('СПРАВКА ОБ ОБУЧЕНИИ','СПРАВКА О ПРАКТИКЕ')
    assert recover(text, bind(text)) == bind(text)


def test_duplicates_conflicts_and_visible_blanks_preserved():
    text=TEXT+'Журавлев Егор Данилович является студентом второго курса\n'
    assert recover(text, bind(text)) == bind(text)
    text=TEXT+'ФИО студента: \nФорма обучения: \nПериод обучения: \n'
    result=recover(text,bind(text))
    assert result['fields']['student_name'] is None
    assert result['fields']['study_form'] is None
    assert result['fields']['study_start'] is None
    text=TEXT+'Название вуза: Другое учреждение\n'
    assert recover(text,bind(text))['fields']['university']=='Другое учреждение'


def test_conflicting_universities_invalid_period_and_header_duplicates_abstain():
    text=TEXT+'«Другой университет побережья»\n14.03.2032 № КР-99\n'
    assert recover(text,bind(text))['fields']['university'] is None
    text=TEXT.replace('01.09.2031 - 30.06.2035','31.02.2031 - 30.06.2035')
    assert recover(text,bind(text))['fields']['study_start'] is None
    text='15.03.2032 № АБ-2\n'+TEXT
    assert recover(text,bind(text))['fields']['document_number'] is None
