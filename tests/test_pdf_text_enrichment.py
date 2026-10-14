import copy
import pytest
from dekanat import pdf_text

def empty():return {'value':None,'status':'not_found','confidence':0,'evidence':None}

def setup(monkeypatch):
    monkeypatch.setattr(pdf_text,'inspect_native_pdf',lambda _: {'eligible':True})
    monkeypatch.setattr(pdf_text,'native_lines',lambda _: [{'text':'literal'}])
    monkeypatch.setattr(pdf_text,'detect_type',lambda _: 'leave')
    monkeypatch.setattr(pdf_text,'extract_candidate',lambda *args: ({'group':{'value':'Ф-31','status':'found','confidence':1,'evidence':{'text':'Группы № Ф-31','page':0,'bbox':[0,0,100,20],'method':'literal'}}},[]))

def test_addition_requires_review_and_preserves_provenance(monkeypatch):
    setup(monkeypatch);fields={'group':empty()}
    result=pdf_text.enrich_pdf(b'x','form.pdf',fields,'leave',None)
    f=fields['group'];assert result['applied'] and f['value']=='Ф-31'
    assert f['status']=='uncertain' and f['confidence']==.5 and f['semantic_confidence'] is None
    assert f['source_confidence']==1 and f['evidence']['source']=='visible_pdf_text'

@pytest.mark.parametrize('status,value',[('found','Ф-30'),('uncertain','Ф-30'),('conflict',None),('not_found','Ф-30')])
def test_nonempty_and_conflict_preserved(monkeypatch,status,value):
    setup(monkeypatch);fields={'group':dict(empty(),status=status,value=value)};before=copy.deepcopy(fields)
    assert not pdf_text.enrich_pdf(b'x','form.pdf',fields,'leave',None)['applied']
    assert fields==before

@pytest.mark.parametrize('case',['image','rotation','ineligible','empty','mismatch','parser_error'])
def test_fallback_keeps_fields(monkeypatch,case):
    setup(monkeypatch);fields={'group':empty()};before=copy.deepcopy(fields);name='form.pdf';orientation=None
    if case=='image':name='image.jpg'
    if case=='rotation':orientation={'pages':[{'applied':True}]}
    if case=='ineligible':monkeypatch.setattr(pdf_text,'inspect_native_pdf',lambda _: {'eligible':False})
    if case=='empty':monkeypatch.setattr(pdf_text,'native_lines',lambda _: [])
    if case=='mismatch':monkeypatch.setattr(pdf_text,'detect_type',lambda _: 'practice')
    if case=='parser_error':
        def fail(*args):raise ValueError('bad native input')
        monkeypatch.setattr(pdf_text,'extract_candidate',fail)
    assert not pdf_text.enrich_pdf(b'x',name,fields,'leave',None,orientation=orientation)['applied']
    assert fields==before

def test_uncertain_native_candidate_not_copied(monkeypatch):
    setup(monkeypatch);monkeypatch.setattr(pdf_text,'extract_candidate',lambda *args: ({'group':{'value':'Ф-31','status':'conflict'}},[]))
    fields={'group':empty()};assert not pdf_text.enrich_pdf(b'x','form.pdf',fields,'leave',None)['applied']

def test_geometry_transformed_to_display_page(monkeypatch):
    setup(monkeypatch);fields={'group':empty()}
    pdf_text.enrich_pdf(b'x','form.pdf',fields,'leave',None,
        preprocessing=[{'rectified_to_input':[[1,0,-10],[0,1,-20],[0,0,1]]}])
    evidence=fields['group']['evidence']
    assert evidence['bbox']==[10,20,110,40] and evidence['source_bbox']==[0,0,100,20]
    assert evidence['coordinate_space']=='rectified_page_pixels'

def test_singular_geometry_falls_back_without_partial_update(monkeypatch):
    setup(monkeypatch);fields={'group':empty()};before=copy.deepcopy(fields)
    report=pdf_text.enrich_pdf(b'x','form.pdf',fields,'leave',None,
        preprocessing=[{'rectified_to_input':[[0,0,0],[0,0,0],[0,0,0]]}])
    assert not report['applied'] and fields==before
