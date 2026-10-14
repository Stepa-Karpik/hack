import pytest
from dekanat.extraction import extract
from dekanat.field_validation import validate_fields


def read(text, kind='study', confidence=.8):
    return extract([{'text':text,'confidence':confidence,'bbox':[0,0,900,30],'page':0}],kind)


@pytest.mark.parametrize('space', [' ', '   ', '\t', '\u00a0', '\u2003'])
def test_leading_whitespace_keeps_period_and_original_evidence(space):
    text=space+'Период обучения: 01.09.2024 - 30.06.2028. Зачислен приказом ректора'
    fields=read(text)
    validate_fields(fields)
    f=fields['study_period']
    assert (f['value'],f['status'])==('01.09.2024 - 30.06.2028','found')
    assert f['evidence']['text']==text and f['confidence']==.8


@pytest.mark.parametrize('text', ['  Курс — обучения = 2', '\tКурс   обучения: 2', '\u00a0Курс\tобучения: 2'])
def test_long_alias_with_spaced_dash_or_internal_whitespace(text):
    f=read(text,'leave')['course']
    assert f['value']=='2' and f['evidence']['text']==text


def test_leading_whitespace_does_not_promote_weak_evidence():
    f=read('  Период обучения: 01.09.2024 - 30.06.2028',confidence=.3)['study_period']
    assert f['status']=='uncertain' and f['confidence']==.3


@pytest.mark.parametrize('text',['  Период обученияX: 01.09.2024 - 30.06.2028','  Примечание: Период обучения: 01.09.2024 - 30.06.2028'])
def test_whitespace_does_not_relax_label_boundary_or_anchor(text):
    assert read(text)['study_period']['status']=='not_found'


def test_value_dashes_are_preserved_with_leading_whitespace():
    f=read('  Направление подготовки: Социально-экономические науки')['program']
    assert f['value']=='Социально-экономические науки'
