import copy
from PIL import Image
import pytest
from scripts.experiments.wrapped_names_image_shadow import reread


@pytest.mark.parametrize('status',['found','conflict'])
def test_confirmed_fields_do_not_load_extra_reader(monkeypatch,status):
    import dekanat.ocr as ocr
    def forbidden(*args,**kwargs):raise AssertionError('Reader should not load')
    monkeypatch.setattr(ocr,'get_reader',forbidden)
    assert not reread([],{'fields':{'university':{'status':status}}},{'university':'Университет <Новый'},{})['attempted']


@pytest.mark.parametrize('tail,accepted',[('«Новый»',True),('«Другой»',False)])
def test_reread_uses_selected_rows_without_mutating_values(monkeypatch,tail,accepted):
    import dekanat.ocr as ocr
    calls=[]
    class Reader:
        def recognize(self,image,**kwargs):
            calls.append(image.shape)
            text='Название вуза: Университет' if len(calls)%2 else tail
            return [(None,text,.9)]
    monkeypatch.setattr(ocr,'quote_state',lambda:True)
    monkeypatch.setattr(ocr,'get_reader',lambda *args,**kwargs:Reader())
    lines=[{'text':'Название вуза: Университет','bbox':[10,10,300,40],'page':0},
           {'text':'<Новый','bbox':[10,55,150,85],'page':0}]
    analysis={'fields':{'university':{'status':'uncertain'}},'ocr':{'lines':lines}}
    fields={'university':'Университет <Новый'};initial=copy.deepcopy(fields)
    result=reread([Image.new('RGB',(500,200),'white')],analysis,fields,{})
    assert bool(result['accepted']) is accepted
    assert result['semantic_confidence'] is None and len(calls)==4
    assert fields==initial
