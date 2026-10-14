from scripts.unified.text_binding import bind


def test_literal_offsets_and_calendar_dates():
    text = 'СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: Еремина Лада Львовна\nДата выдачи: 3 ноября 2028 года\n'
    result = bind(text)
    assert result['fields']['student_name'] == 'Еремина Лада Львовна'
    assert result['fields']['issue_date'] == '2028-11-03'
    span = result['audit']['student_name']['candidates'][0]['ocr_text_span']
    assert text[slice(*span)] == 'ФИО студента: Еремина Лада Львовна'
    assert result['audit']['student_name']['bbox'] is None
    assert result['audit']['student_name']['semantic_confidence'] is None


def test_blank_does_not_borrow_next_line_or_id():
    result = bind('СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: ____\nКовалев Яромир Эдуардович\nИдентификатор образца: open-001')
    assert result['fields']['student_name'] is None
    assert result['fields']['document_number'] is None


def test_conflicting_values_and_blank_duplicate_abstain():
    for second in ('Поляков Вадим Львович', ''):
        result = bind('СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: Зубов Герман Ильич\nФИО студента: ' + second)
        assert result['fields']['student_name'] is None
        assert result['audit']['student_name']['status'] == 'conflict'


def test_graphic_captions_never_set_marks():
    result = bind('СПРАВКА ОБ ОБУЧЕНИИ\nПодпись: Иванов\nПечать: М.П.\nУЧЕБНАЯ ПЕЧАТЬ')
    assert result['fields']['signature_present'] is None
    assert result['fields']['seal_present'] is None
    assert not result['complete_document_check']


def test_invalid_dates_unknown_conflicting_title_and_truncation():
    text = 'СПРАВКА ОБ ОБУЧЕНИИ\nДата выдачи: 31.02.2028'
    assert bind(text)['fields']['issue_date'] is None
    assert bind(text + '\nЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК')['document_type'] is None
    assert bind('Пример: СПРАВКА ОБ ОБУЧЕНИИ')['document_type'] is None
    assert bind(text, truncated=True)['fields'] == {}


def test_official_practice_title_and_uncorrected_literal():
    result = bind('СПРАВКА О ПРАКТИКЕ\nОценка: заутено\nДата начала практики: 1 июня 2028 года')
    assert result['document_type'] == 'internship_certificate'
    assert result['fields']['grade'] == 'заутено'
    assert result['fields']['internship_start'] == '2028-06-01'


def test_mark_probe_invalid_is_unknown_never_absent():
    from scripts.unified.marks_probe import parse_marks
    assert parse_marks('{"signature_present":false,"seal_present":true}') == {'signature_present': False, 'seal_present': True}
    for raw in ('Подпись: ____ М.П.', '{"signature_present":"false","seal_present":false}',
                '{"signature_present":true}', '{"signature_present":false,"seal_present":false,"extra":0}'):
        assert parse_marks(raw) is None
