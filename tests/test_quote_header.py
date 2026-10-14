from copy import deepcopy
import pytest
from PIL import Image
import dekanat.ocr as ocr
from dekanat.extraction import extract


def line(text,y,x=20,page=0,confidence=.9):
    return {'text':text,'bbox':[x,y,x+300,y+30],'page':page,'confidence':confidence}


def recover(monkeypatch,tmp_path,lines,reading=' «Учебный университет«',confidence=.8):
    class Reader:
        def recognize(self,*args,**kwargs):return [(None,reading,confidence)]
    monkeypatch.setattr(ocr,'get_reader',lambda *a,**kw:Reader())
    weights=tmp_path/'weights.pt';weights.write_bytes(b'unchanged')
    fields=extract(lines,'study')
    result=ocr.recover_quote_fields([Image.new('RGB',(500,500),'white')]*2,lines,fields,'study',weights=weights)
    return fields,result


def test_quoted_header_recovers_exact_name_with_context_and_raw_source(monkeypatch,tmp_path):
    lines=[line('высшего образования',20),line('(Учебный университетэ',60)]
    original=deepcopy(lines)
    fields,result=recover(monkeypatch,tmp_path,lines)
    f=fields['university']
    assert f['value']=='Учебный университет' and f['status']=='found' and f['confidence']==.8
    assert result['accepted']==['university'] and result['attempts']==1
    assert f['evidence']['baseline_text']==lines[1]['text']
    assert f['evidence']['context']==lines[0] and lines==original


@pytest.mark.parametrize('change',['page','column','gap','context','institution'])
def test_header_requires_same_page_nearby_overlap_and_explicit_context(monkeypatch,tmp_path,change):
    lines=[line('высшего образования',20),line('(Учебный университетэ',60)]
    if change=='page':lines[0]['page']=1
    if change=='column':lines[0]['bbox']=[350,20,490,50]
    if change=='gap':lines[1]['bbox']=[20,200,320,230]
    if change=='context':lines[0]['text']='Декан факультета высшего образования'
    if change=='institution':lines[1]['text']='(Информационные системыэ'
    monkeypatch.setattr(ocr,'get_reader',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No target')))
    fields=extract(lines,'study')
    result=ocr.recover_quote_fields([],lines,fields,'study',weights='unused.pt')
    assert result['attempts']==0 and fields['university']['value'] is None


@pytest.mark.parametrize('reading',['Учебный университет','«Учебный университет» адрес: улица 1','«Информационные системы»'])
def test_reread_requires_entire_quoted_institution_name(monkeypatch,tmp_path,reading):
    fields,result=recover(monkeypatch,tmp_path,[line('высшего образования',20),line('(Учебный университетэ',60)],reading=reading)
    assert result['accepted']==[] and fields['university']['value'] is None


@pytest.mark.parametrize('weak',['context','baseline','reread'])
def test_low_confidence_any_supporting_row_is_not_promoted(monkeypatch,tmp_path,weak):
    lines=[line('высшего образования',20),line('(Учебный университетэ',60)]
    if weak=='context':lines[0]['confidence']=.3
    if weak=='baseline':lines[1]['confidence']=.3
    fields,result=recover(monkeypatch,tmp_path,lines,confidence=.3 if weak=='reread' else .8)
    assert result['accepted']==[] and fields['university']['value'] is None


def test_existing_university_not_changed_even_if_header_differs(monkeypatch,tmp_path):
    lines=[line('высшего образования',20),line('(Другой университетэ',60),line('Название вуза: Исходный университет',200)]
    fields,result=recover(monkeypatch,tmp_path,lines,reading='«Другой университет»')
    assert fields['university']['value']=='Исходный университет' and result['attempts']==0


def test_existing_uncertain_value_is_not_overwritten(monkeypatch,tmp_path):
    lines=[line('высшего образования',20),line('(Другой университетэ',60),line('Название вуза: Исходный университет',200,confidence=.3)]
    fields,result=recover(monkeypatch,tmp_path,lines,reading='«Другой университет»')
    assert fields['university']['value']=='Исходный университет' and fields['university']['status']=='uncertain'
    assert result['attempts']==0


def test_distinct_quoted_headers_are_not_arbitrarily_selected(monkeypatch,tmp_path):
    readings=iter(['«Первый университет»','«Второй университет»'])
    class Reader:
        def recognize(self,*args,**kwargs):return [(None,next(readings),.9)]
    monkeypatch.setattr(ocr,'get_reader',lambda *a,**kw:Reader())
    weights=tmp_path/'weights.pt';weights.write_bytes(b'unchanged')
    lines=[line('высшего образования',20),line('(Первый университетэ',60),line('высшего образования',160),line('(Второй университетэ',200)]
    fields=extract(lines,'study')
    result=ocr.recover_quote_fields([Image.new('RGB',(500,500),'white')],lines,fields,'study',weights=weights)
    assert result['attempts']==2 and result['accepted']==[] and fields['university']['value'] is None
