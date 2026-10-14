from dekanat.extraction import extract
from tests.test_narrative import rows


def test_named_study_subject_keeps_exact_source_name():
    fields=extract(rows('Иванов Алексей Петрович является студентом третьего курса'), 'study')
    assert fields['student_name']['value']=='Иванов Алексей Петрович'
    assert fields['student_name']['evidence']['rule']=='named_student_subject'


def test_confirmed_subject_is_not_executor_name():
    f=extract(rows('Настоящим подтверждается; что Крылова Мария Андреевна обучается',
                   'Исполнитель Соколова Анна Сергеевна'), 'study')
    assert f['student_name']['value']=='Крылова Мария Андреевна'


def test_wrapped_reason_retains_last_word_without_partial_conflict():
    f=extract(rows('Прошу предоставить мне академический отпуск с 15.10.2026 по',
                   '14.10.2027 по семейным обстоятельствам в связи с необходимостью ухода за',
                   'ребёнком.'), 'leave')
    assert f['reason']['value']=='по семейным обстоятельствам в связи с необходимостью ухода за ребёнком'
    assert f['reason']['status']=='found'
    assert f['start_date']['value']=='15.10.2026'


def test_request_with_two_explicit_dates_tolerates_missing_preposition():
    f=extract(rows('Прошу предоставить мне академический отпуск 20.10.2026 по',
                   '19.04.2027 по состоянию здоровья в связи с необходимостью длительного',
                   'лечения:'), 'leave')
    assert f['end_date']['value']=='19.04.2027'
    assert f['reason']['value'].endswith('лечения')


def test_long_application_label_does_not_leak_into_value():
    assert extract(rows('Дата подачи заявления: 10.10.2026'), 'leave')['application_date']['value']=='10.10.2026'


def test_period_stops_before_enrollment_order():
    f=extract(rows('Период обучения: 01.09.2024 30.06.2028. Зачислен приказом ректора',
                   'от 29.08.2024 № 214-ст.'), 'study')
    assert f['study_period']['value']=='01.09.2024 - 30.06.2028'


def test_applicant_signature_block_name_and_course():
    f=extract(rows('от студентки 3 курса', 'Заявитель', 'Смирнова Анна Дмитриевна'), 'leave')
    assert f['student_name']['value']=='Смирнова Анна Дмитриевна'
    assert f['course']['value']=='3'


def test_different_pages_do_not_complete_request():
    f=extract(rows('Прошу предоставить мне академический отпуск с 15.10.2026 по')+
              rows('14.10.2027 по семейным обстоятельствам.',page=1), 'leave')
    assert f['start_date']['value'] is None


def test_staff_title_is_not_date_even_after_empty_label():
    assert extract(rows('Выдана для представления по месту требования',
                        'Начальник учебного управления'), 'study')['issue_date']['value'] is None


def test_new_low_confidence_subject_stays_uncertain():
    assert extract(rows('Иванов Алексей Петрович является студентом',confidence=.4), 'study')['student_name']['status']=='uncertain'
