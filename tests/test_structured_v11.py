from dekanat.extraction import extract, canonical_value, same_supervisor
from tests.test_narrative import rows


def test_outgoing_header_not_admission_order():
    f=extract(rows('Исх: Ng УО-09/114 от 09.10.2026','Приказ от 28.08.2025 № 198-ст'), 'study')
    assert f['document_number']['value']=='УО-09/114'
    assert f['issue_date']['value']=='09.10.2026'


def test_outgoing_number_alone_does_not_create_date():
    f=extract(rows('Исходящий N К-76/2026'), 'practice')
    assert f['document_number']['value']=='К-76/2026'
    assert f['issue_date']['value'] is None


def test_explicit_form_stops_at_next_sentence_marker():
    assert canonical_value('study_form','очно-заочная Нормативный')=='очно-заочная'
    assert canonical_value('study_form','очная Обучение осуществляется за счёт средств физических лиц')=='очная'
    assert canonical_value('study_form','очная заочная')=='очная заочная'


def test_grade_stops_at_characteristic_but_not_other_rating():
    assert canonical_value('grade','хорошо Подробная характеристика и перечень работ')=='хорошо'
    assert canonical_value('grade','хорошо отлично')=='хорошо отлично'


def test_long_supervisor_alias_does_not_include_label_words():
    f=extract(rows('Руководитель практики от организации: Кузнецов Игорь Валерьевич;'), 'practice')
    assert f['supervisor']['value']=='Кузнецов Игорь Валерьевич'


def test_wrapped_table_supervisor_label_needs_continuation():
    f=extract(rows('Руководитель практики от Соколов Андрей Викторович','организации'), 'practice')
    assert f['supervisor']['value']=='Соколов Андрей Викторович'
    assert f['supervisor']['evidence']['label_continuation']['text']=='организации'
    f=extract(rows('Руководитель практики от Соколов Андрей Викторович'), 'practice')
    assert f['supervisor']['value']=='от Соколов Андрей Викторович'


def test_supervisor_initials_match_only_existing_explicit_full_name():
    assert same_supervisor('Кузнецов Игорь Валерьевич','ИВ: Кузнецов')
    assert not same_supervisor('Кузнецов Игорь Валерьевич','П.В. Кузнецов')
    assert not same_supervisor('Кузнецов Игорь Валерьевич','И.В. Соколов')
    f=extract(rows('Руководитель практики: Кузнецов Игорь Валерьевич',
                   'Руководитель практики: ИВ: Кузнецов'), 'practice')
    assert f['supervisor']['status']=='found'
    assert f['supervisor']['value']=='Кузнецов Игорь Валерьевич'
    assert len(f['supervisor']['corroborating_evidence'])==1


def test_different_person_keeps_conflict():
    f=extract(rows('Руководитель практики: Кузнецов Игорь Валерьевич',
                   'Руководитель практики: П.В. Кузнецов'), 'practice')
    assert f['supervisor']['status']=='conflict'


def test_department_role_is_not_a_second_person():
    f=extract(rows('Руководитель практики: Кузнецов Игорь Валерьевич',
                   'Руководитель аналитического отдела: Практикант выполнял сбор данных'), 'practice')
    assert f['supervisor']['status']=='found'


def test_low_confidence_header_not_promoted():
    assert extract(rows('Исходящий N К-76/2026',confidence=.4),'practice')['document_number']['status']=='uncertain'


def test_wrapped_label_keeps_low_confidence_of_continuation():
    source=rows('Руководитель практики от Соколов Андрей Викторович','организации')
    source[1]['confidence']=.4
    f=extract(source,'practice')['supervisor']
    assert f['value']=='Соколов Андрей Викторович'
    assert f['status']=='uncertain' and f['confidence']==.4
    assert len(f['evidence']['parts'])==2
