import copy
import json
import pytest
from scripts.unified.contract import KEYS, MARKS, parse, official_result


def document():
    keys=KEYS['academic_leave_application']
    return {'document_type':'academic_leave_application',
            'fields':{k:False if k in MARKS else None for k in keys},
            'boxes':{k:None for k in keys}}


def test_blank_document_never_becomes_complete_and_unknown_question_has_no_answer():
    prediction=parse(json.dumps(document()))
    result=official_result(prediction,[{'question_id':'q','question':'Где находится герб?'}])
    assert result['validation']['status']=='missing_fields'
    assert not result['answers'][0]['answerable']
    assert all(v['semantic_confidence'] is None for v in result['audit'].values())


@pytest.mark.parametrize('bad',['false',0,1,None])
def test_mark_strings_and_numbers_are_rejected(bad):
    d=document();d['fields']['signature_present']=bad
    with pytest.raises(ValueError):parse(json.dumps(d))


@pytest.mark.parametrize('bbox',[[0,0,1001,100],[0,0,float('nan'),100],[10,0,0,10],[0,1,2],['1',2,3,4]])
def test_invalid_generated_geometry_is_rejected(bbox):
    d=document();d['fields']['student_name']='Тестовое имя';d['boxes']['student_name']=bbox
    with pytest.raises(ValueError):parse(json.dumps(d))


def test_missing_cannot_have_box_and_extra_keys_are_rejected():
    d=document();d['boxes']['student_name']=[0,0,100,100]
    with pytest.raises(ValueError):parse(json.dumps(d))
    d=document();d['fields']['unexpected']='value'
    with pytest.raises(ValueError):parse(json.dumps(d))


def test_value_and_generated_box_keep_uncertainty_and_input_is_not_modified():
    d=document();d['fields']['student_name']='Родников Денис Сергеевич';d['boxes']['student_name']=[10,20,100,40]
    before=copy.deepcopy(d);result=official_result(parse(json.dumps(d)))
    assert d==before
    assert result['fields']['student_name']==d['fields']['student_name']
    assert result['audit']['student_name']['status']=='uncertain'
    assert not result['audit']['student_name']['geometry_verified']
