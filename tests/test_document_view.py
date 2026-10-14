import copy
import math
from PIL import Image
from scripts.participantkit.document_view import build_document_view

def test_view_links_exact_rectified_evidence_and_keeps_uncertainty():
    pages=[Image.new('RGB',(200,400),'white')]
    result={'fields':{'issue_date':'2026-10-08','signature_present':True,'seal_present':False,'study_start':'2024-09-01','study_end':'2028-06-30'}}
    audit={'bindings':{},'analysis':{'fields':{
        'issue_date':{'status':'found','evidence':{'page':0,'bbox':[20,40,100,80]}},
        'signature':{'status':'uncertain','evidence':{'page':0,'bbox':[30,300,90,330]}},
        'study_period':{'status':'found','evidence':{'page':0,'bbox':[10,200,150,220]}}}}}
    saved=copy.deepcopy((result,audit));view=build_document_view(pages,result,audit)
    assert (result,audit)==saved
    assert view['pages'][0]['width']==200 and view['pages'][0]['image'].startswith('data:image/jpeg;base64,')
    assert view['regions'][0]['bbox']==[.1,.1,.5,.2]
    assert [r['field'] for r in view['regions']]==['issue_date','signature_present','study_start','study_end']
    assert view['regions'][1]['status']=='uncertain' and view['regions'][1]['semantic_confidence'] is None

def test_binding_wins_without_falling_back_to_stale_raw_geometry():
    result={'fields':{'issue_date':'2026-10-08'}}
    audit={'bindings':{'issue_date':{'status':'uncertain','evidence':{}}},'analysis':{'fields':{'issue_date':{'status':'found','evidence':{'page':0,'bbox':[1,1,20,20]}}}}}
    assert build_document_view([Image.new('RGB',(50,50))],result,audit)['regions']==[]

def test_invalid_geometry_and_native_coordinates_are_not_guessed():
    fields={};raw={}
    for i,e in enumerate([{'page':0,'bbox':[0,0,math.nan,10]}, {'page':1,'bbox':[0,0,10,10]},
        {'page':False,'bbox':[0,0,10,10]}, {'page':0,'bbox':[-1,0,10,10]},
        {'page':0,'bbox':[0,0,60,10]}, {'page':0,'bbox':[0,0,10,10],'coordinate_space':'native_pdf_points'}]):
        fields[str(i)]='value';raw[str(i)]={'status':'found','evidence':e}
    assert build_document_view([Image.new('RGB',(50,50))],{'fields':fields},{'analysis':{'fields':raw}})['regions']==[]


def test_multi_page_geometry_uses_each_pages_own_dimensions():
    pages=[Image.new('RGB',(200,400)),Image.new('RGB',(600,300))]
    result={'fields':{'university':'A','program':'B'}}
    audit={'analysis':{'fields':{'university':{'status':'found','evidence':{'page':0,'bbox':[20,40,100,80]}},'program':{'status':'uncertain','evidence':{'page':1,'bbox':[60,30,300,60]}}}}}
    view=build_document_view(pages,result,audit)
    assert [r['page'] for r in view['regions']]==[0,1]
    assert view['regions'][0]['bbox']==view['regions'][1]['bbox']==[.1,.1,.5,.2]
    assert [(p['width'],p['height']) for p in view['pages']]==[(200,400),(600,300)]
