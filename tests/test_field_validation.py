import pytest
from dekanat.field_validation import validate_fields


def field(value,status='found'):
    return {'value':value,'status':status,'confidence':.97,'evidence':{'text':'Исходный OCR', 'bbox':[1,2,3,4]}}


@pytest.mark.parametrize('value,expected',[('11.12,2026','11.12.2026'),('1/9/2026','01.09.2026'),('2026-09-01','01.09.2026'),('29.02.2024','29.02.2024')])
def test_date_normalizes_only_explicit_digits(value,expected):
    original=field(value);evidence=original['evidence'];fields={'issue_date':original}
    validate_fields(fields)
    assert original['value']==expected and original['status']=='found'
    assert original['evidence'] is evidence and original['confidence']==.97


@pytest.mark.parametrize('value',['05.10.2','31.04.2026','29.02.2025','1 сентября 2026','О1.09.2026','01.09.2026 extra'])
def test_incomplete_impossible_or_unsupported_dates_require_review(value):
    original=field(value);validate_fields({'issue_date':original})
    assert original['value']==value and original['status']=='uncertain'
    assert original['validation'][0]['raw_value']==value


def test_period_with_comma_dates_and_lost_separator_preserves_source():
    original=field('01.09,2024 30,06,2026')
    validate_fields({'study_period':original})
    assert original['value']=='01.09.2024 - 30.06.2026'
    assert original['validation'][0]['raw_value']=='01.09,2024 30,06,2026'


@pytest.mark.parametrize('value',['01.09.2026 - 30.06.2026','01.09.2026 - 30.06.2','01.09.2026 - 30.06.2027 - 01.07.2027'])
def test_invalid_or_ambiguous_period_not_guessed(value):
    original=field(value);validate_fields({'study_period':original})
    assert original['status']=='uncertain' and original['value']==value


@pytest.mark.parametrize('status',['uncertain','conflict'])
def test_normalization_never_promotes_uncertain_or_conflicting_field(status):
    original=field('11.12,2026',status);validate_fields({'issue_date':original})
    assert original['status']==status


def test_non_date_fields_and_missing_values_are_untouched():
    number=field('УЧ-72');missing=field(None,'not_found')
    validate_fields({'document_number':number,'issue_date':missing})
    assert number==field('УЧ-72') and missing==field(None,'not_found')


def test_invalid_date_blocks_completeness_and_direct_answer():
    from dekanat.reasoning import answer
    from dekanat.schema import load_policy,SCHEMAS
    fields={key:field('confirmed') for key in SCHEMAS['leave']['fields']}
    fields.update(start_date=field('01.10.2026'),end_date=field('02.10.2027'),application_date=field('05.10.2'),signature=field(True))
    validate_fields(fields)
    policy=load_policy()
    assert answer('Все ли обязательные сведения есть в документе?','leave',fields,policy)['status']=='insufficient'
    assert answer('Какая дата заявления?','leave',fields,policy)['status']=='insufficient'
