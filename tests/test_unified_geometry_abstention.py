import copy
import json
import pytest
from scripts.unified.contract import KEYS,MARKS
from scripts.unified.geometry_contract import parse_abstaining


def record():
    return {'document_type':'academic_leave_application',
            'fields':{k:False if k in MARKS else None for k in KEYS['academic_leave_application']},
            'boxes':{k:None for k in KEYS['academic_leave_application']}}


def test_invalid_geometry_abstains_without_rewriting_values_or_input():
    raw=record();raw['fields']['student_name']='Неизвестное имя'
    raw['boxes']['student_name']=[300,20,200,50]
    raw['boxes']['signature_present']=[1,2,3,4]
    before=copy.deepcopy(raw)
    prediction,audit=parse_abstaining(json.dumps(raw))
    assert raw==before and prediction['fields']==raw['fields']
    assert prediction['boxes']['student_name'] is None
    assert prediction['boxes']['signature_present'] is None
    assert not audit['strict_accepted'] and len(audit['abstentions'])==2
    assert audit['abstentions'][0]['raw_box']==[300,20,200,50]


@pytest.mark.parametrize('defect',['empty','bad_bool','omitted_box','extra_field'])
def test_geometry_abstention_never_repairs_scalar_or_schema_errors(defect):
    raw=record()
    if defect=='empty':raw['fields']['student_name']=''
    if defect=='bad_bool':raw['fields']['signature_present']='false'
    if defect=='omitted_box':del raw['boxes']['student_name']
    if defect=='extra_field':raw['fields']['extra']='invented'
    with pytest.raises(ValueError):parse_abstaining(json.dumps(raw))
