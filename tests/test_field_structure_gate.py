from scripts.compare_field_structure import compare


def test_correct_value_abstention_fails_even_with_same_exact_match_count():
    key = ('study', 'original', 'program')
    before = {key:dict(value='a', status='found', correct=True)}
    after = {key:dict(value='a', status='uncertain', correct=True)}
    assert not compare(before, after)['passed']
    assert compare(before, after)['correct_found_lost'] == [key]


def test_wrong_value_abstention_is_allowed_without_claiming_correction():
    key = ('study', 'original', 'program')
    before = {key:dict(value='wrong', status='found', correct=False)}
    after = {key:dict(value='wrong', status='uncertain', correct=False)}
    result = compare(before, after)
    assert result['passed'] and result['conditions']['original']['after_correct'] == 0
