import copy

from scripts.experiments.leave_prose import recover
from scripts.participantkit.format_v1 import MISSING


def fixture():
    text = ['От Лаптевой Марии Денисовны', 'Студентки группы МТ-721/2028',
            '14 февраля 2028 года', 'Заявление на академический отпуск',
            'Прошу в связи с уходом за ребёнком оформить академический отпуск с 01.03.2028',
            'г. по 01.09.2028 г.']
    rows = [{'text': t, 'page': 0, 'confidence': .9, 'bbox': [100, i*35, 900, i*35+25]}
            for i, t in enumerate(text)]
    keys = ['student_name', 'group', 'course', 'leave_reason', 'leave_start', 'leave_end', 'application_date']
    fields = {k: MISSING for k in keys}
    fields['signature_present'] = True
    raw = {k: {'value': None, 'status': 'not_found'} for k in
           ['student_name', 'group', 'course', 'reason', 'start_date', 'end_date', 'application_date']}
    return fields, {}, {'type': 'leave', 'fields': raw, 'ocr': {'lines': rows}}


def test_literal_sender_case_complete_period_no_course_inference():
    fields, bindings, analysis = fixture()
    snapshot = copy.deepcopy((fields, bindings, analysis))
    result, evidence, changes = recover(fields, bindings, analysis)
    assert result['student_name'] == 'Лаптевой Марии Денисовны'
    assert result['group'] == 'МТ-721/2028'
    assert result['application_date'] == '2028-02-14'
    assert result['leave_reason'] == 'уходом за ребёнком'
    assert result['leave_start'] == '2028-03-01'
    assert result['leave_end'] == '2028-09-01'
    assert result['course'] == MISSING and result['signature_present'] is True
    assert len(changes) == 6
    assert all(e['status'] == 'uncertain' and e['semantic_confidence'] is None for e in evidence.values())
    assert snapshot == (fields, bindings, analysis)


def test_nonempty_and_conflict_preserved():
    fields, bindings, analysis = fixture()
    fields['student_name'] = 'Прежнее буквальное имя'
    bindings['group'] = {'status': 'conflict'}
    analysis['fields']['start_date']['status'] = 'conflict'
    result, _, _ = recover(fields, bindings, analysis)
    assert result['student_name'] == fields['student_name']
    assert result['group'] == result['leave_start'] == MISSING


def test_wrong_type_duplicate_sender_and_staff_date_not_borrowed():
    fields, bindings, analysis = fixture()
    analysis['type'] = 'practice'
    assert recover(fields, bindings, analysis)[2] == []
    analysis['type'] = 'leave'
    analysis['ocr']['lines'].append({**analysis['ocr']['lines'][0], 'text': 'От Михайлова Олега Петровича'})
    result, _, _ = recover(fields, bindings, analysis)
    assert result['student_name'] == result['group'] == result['application_date'] == MISSING
    _, _, analysis = fixture()
    analysis['ocr']['lines'][2]['bbox'][0] = 1000
    assert recover(fields, bindings, analysis)[0]['application_date'] == MISSING


def test_cross_page_invalid_date_and_unanchored_attachment_not_inferred():
    fields, bindings, analysis = fixture()
    analysis['ocr']['lines'][5]['page'] = 1
    assert recover(fields, bindings, analysis)[0]['leave_end'] == MISSING
    _, _, analysis = fixture()
    analysis['ocr']['lines'][4]['text'] = analysis['ocr']['lines'][4]['text'].replace('01.03.2028', '31.02.2028')
    assert recover(fields, bindings, analysis)[0]['leave_start'] == MISSING
    analysis['ocr']['lines'][4]['text'] = 'Листок нетрудоспособности по беременности'
    result, _, _ = recover(fields, bindings, analysis)
    assert result['leave_reason'] == result['leave_start'] == MISSING


def test_symbol_anchor_only_literal_reason_and_bad_geometry_rejected():
    fields, bindings, analysis = fixture()
    analysis['ocr']['lines'][4]['text'] = analysis['ocr']['lines'][4]['text'].replace('связи с', 'связи €')
    result, _, _ = recover(fields, bindings, analysis)
    assert result['leave_reason'] == 'уходом за ребёнком'
    analysis['ocr']['lines'][4]['bbox'][0] = float('nan')
    result, _, _ = recover(fields, bindings, analysis)
    assert result['leave_reason'] == result['leave_start'] == MISSING
