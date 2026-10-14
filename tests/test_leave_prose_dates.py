from test_leave_prose_experiment import fixture
from scripts.experiments.leave_prose_dates import recover
from scripts.participantkit.format_v1 import MISSING


def test_literal_year_abbreviation_without_punctuation_and_colon():
    for abbreviation in ['г', 'Г', 'г:']:
        f, b, a = fixture()
        a['ocr']['lines'][5]['text'] = abbreviation + ' по 01.09.2028 г.'
        result, evidence, _, _ = recover(f, b, a)
        assert result['leave_start'] == '2028-03-01'
        assert result['leave_end'] == '2028-09-01'
        assert evidence['leave_start']['semantic_confidence'] is None


def test_abbreviation_does_not_relax_request_or_conflict_guards():
    f, b, a = fixture()
    a['ocr']['lines'][5]['text'] = 'Г по 01.09.2028 г.'
    a['ocr']['lines'][4]['text'] = 'Пример: ' + a['ocr']['lines'][4]['text']
    assert recover(f, b, a)[0]['leave_start'] == MISSING
    f, b, a = fixture()
    a['ocr']['lines'][5]['text'] = 'Г по 01.09.2028 г.'
    a['fields']['start_date']['status'] = 'conflict'
    assert recover(f, b, a)[0]['leave_start'] == MISSING
