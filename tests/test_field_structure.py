import pytest
from dekanat.extraction import extract
from dekanat.field_validation import validate_fields


@pytest.mark.parametrize('dash', ['-', '–', '—'])
def test_spaced_dash_in_long_label_preserves_source_offsets(dash):
    text = f'Курс {dash} обучения = 1'
    field = extract([{'text':text,'confidence':.8,'bbox':[0,0,250,30],'page':0}], 'leave')['course']
    assert field['value'] == '1' and field['status'] == 'found'
    assert field['evidence']['text'] == text


def test_label_tolerance_does_not_remove_dashes_in_values():
    field = extract([{'text':'Направление подготовки: Социально-экономические науки','confidence':.9,'bbox':[0,0,700,30],'page':0}], 'study')['program']
    assert field['value'] == 'Социально-экономические науки'


@pytest.mark.parametrize('value', ['09.о3.01 Информатика', 'O9.03.01 Информатика'])
def test_ambiguous_code_is_preserved_and_never_guessed(value):
    field = {'value':value,'status':'found','confidence':.95,'evidence':{'text':value}}
    validate_fields({'program':field})
    assert field['status'] == 'uncertain' and field['value'] == value
    assert field['confidence'] == .95 and field['evidence']['text'] == value


@pytest.mark.parametrize('value', ['09.03.01 Информатика', 'Информатика', 'AB.03.01 Test'])
def test_other_program_formats_are_not_restricted(value):
    field = {'value':value,'status':'found'}
    validate_fields({'program':field})
    assert field == {'value':value,'status':'found'}
