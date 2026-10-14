from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/participantkit'))
from mark_guard import reject_printed_signature,printed_caption


def analysis(text='Подпись сотрудника:',status='uncertain',box=None,page=0):
    return {'fields':{'signature':{'value':True,'status':status,'confidence':.4,
        'evidence':{'method':'finetuned_yolov8n','bbox':box or [0,0,200,30],'page':0}}},
        'ocr':{'lines':[{'text':text,'bbox':[0,0,200,30],'page':page,'confidence':.95}]}}


def test_weak_caption_is_rejected_without_claiming_conclusive_absence():
    fields={'signature_present':True};evidence={}
    result=reject_printed_signature(analysis(),fields,evidence)
    assert result['applied'] and fields['signature_present'] is False
    assert evidence['signature_present']['status']=='uncertain'


@pytest.mark.parametrize('item',[analysis(status='found'),analysis(text='Иванов Иван Иванович'),
    analysis(box=[250,0,450,30]),analysis(page=1),analysis(box=[0,0,600,60])])
def test_positive_name_strong_prediction_different_geometry_are_preserved(item):
    fields={'signature_present':True}
    assert not reject_printed_signature(item,fields,{})['applied']
    assert fields['signature_present'] is True


def test_caption_with_a_persons_name_is_not_empty_printed_caption():
    assert not printed_caption('Подпись сотрудника: Петров И. И.')
    assert printed_caption('СПРАВКА ОБ ОБУЧЕНИИ')
