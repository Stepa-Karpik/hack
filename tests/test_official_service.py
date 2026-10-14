import copy
import pytest
from scripts.participantkit.service import prepare_result,check_request,analyze_document


def source():
    return {'type':'study','fields':{},'ocr':{'lines':[
        {'text':'ФИО студента: Романов Ян Петрович','page':0,'confidence':.9,'bbox':[0,0,350,20]},
        {'text':'Дата выдачи: 03.05.2027','page':0,'confidence':.9,'bbox':[0,40,350,60]}]}}


def test_any_document_can_be_asked_without_manifest_and_source_is_not_mutated():
    analysis=source();before=copy.deepcopy(analysis)
    q=[{'question_id':'custom','question':'Какова дата выдачи?'}]
    result,audit=prepare_result(None,analysis,'study_certificate',q,document_id='user-upload',
        crop_recovery=False,value_quote_recovery=False)
    assert result['answers'][0]['value']=='2027-05-03'
    assert result['answers'][0]['sources']==['field:issue_date']
    assert analysis==before and audit['analysis']==analysis


def test_different_upload_ids_do_not_change_semantic_results():
    a,_=prepare_result(None,source(),'study_certificate',[],document_id='A',crop_recovery=False,value_quote_recovery=False)
    b,_=prepare_result(None,source(),'study_certificate',[],document_id='B',crop_recovery=False,value_quote_recovery=False)
    assert a['fields']==b['fields'] and a['validation']==b['validation']


@pytest.mark.parametrize('kind,questions',[('unsupported',[]),('study_certificate',[{'question_id':'q','question':''}]),
    ('study_certificate',[{'question_id':'q','question':'Что?'}]*2),('study_certificate',{})])
def test_invalid_requests_are_rejected(kind,questions):
    with pytest.raises(ValueError):check_request(kind,questions)


def test_type_mismatch_and_missing_pixels_are_rejected():
    with pytest.raises(ValueError):prepare_result(None,source(),'internship_certificate',[],crop_recovery=False,value_quote_recovery=False)
    with pytest.raises(ValueError):prepare_result(None,source(),'study_certificate',[])


def test_unsupported_upload_is_rejected_before_model_loading():
    with pytest.raises(ValueError):analyze_document(b'abc','test.docx','study_certificate',[])
