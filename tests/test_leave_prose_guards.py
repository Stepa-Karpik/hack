from scripts.experiments.leave_prose import recover as original
from scripts.experiments.leave_prose_guarded import recover
from scripts.participantkit.format_v1 import MISSING
from test_leave_prose_experiment import fixture


def test_staff_date_exposes_original_false_fill_and_guard_preserves_missing():
    fields, bindings, analysis = fixture()
    rows = analysis['ocr']['lines']
    rows[2]['bbox'] = [100, 90, 900, 115]
    rows[3]['bbox'] = [100, 140, 900, 165]
    rows[4]['bbox'] = [100, 180, 900, 205]
    rows[5]['bbox'] = [100, 215, 900, 240]
    rows.append({'text': 'Согласовано деканом', 'page': 0, 'confidence': .9, 'bbox': [100, 65, 900, 85]})
    assert original(fields, bindings, analysis)[0]['application_date'] == '2028-02-14'
    result, _, _, rejected = recover(fields, bindings, analysis)
    assert result['application_date'] == MISSING
    assert {'field': 'application_date', 'reason': 'intervening_staff_context'} in rejected
    assert result['student_name'] == 'Лаптевой Марии Денисовны'


def test_quoted_example_and_negated_request_do_not_fill_period():
    fields, bindings, analysis = fixture()
    analysis['ocr']['lines'][4]['text'] = 'Пример: ' + analysis['ocr']['lines'][4]['text']
    assert original(fields, bindings, analysis)[0]['leave_start'] == '2028-03-01'
    result, _, _, _ = recover(fields, bindings, analysis)
    assert result['leave_start'] == result['leave_end'] == result['leave_reason'] == MISSING
    analysis['ocr']['lines'][4]['text'] = 'Прошу не оформить академический отпуск с 01.03.2028'
    result, _, _, _ = recover(fields, bindings, analysis)
    assert result['leave_start'] == result['leave_end'] == MISSING


def test_positive_literal_controls_still_add_six_fields():
    f, b, a = fixture()
    before = original(f, b, a)
    after = recover(f, b, a)
    assert after[:3] == before and after[3] == []
