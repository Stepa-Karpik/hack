import numpy as np
from PIL import Image

from dekanat import ocr, pipeline, orientation


def line(text, confidence, page=0, box=None):
    return {'text':text,'confidence':confidence,'page':page,'bbox':box or [4,5,10,12],'retried':False}


def test_refinement_uses_final_page_and_strict_confidence_gain(monkeypatch):
    pages=[Image.new('RGB',(20,30),(10,20,30)),Image.new('RGB',(20,30),(90,80,70))]
    lines=[line('old',.4,1),line('stable',.55),line(' ',.2),line('edge',.4),line('outside',.2,box=[40,50,60,70])]
    calls=[]
    class Reader:
        def recognize(self,crop,**kwargs):
            calls.append((crop,kwargs))
            return [(None,'new',.51 if len(calls)==1 else .5)]
    monkeypatch.setattr(ocr,'get_reader',lambda *args:Reader())
    result={'lines':lines,'seconds':1.,'retries':3}
    ocr.refine_uncertain(pages,result)
    assert len(calls)==2
    assert np.array_equal(calls[0][0][0,0],[90,80,70])
    assert calls[0][1]['decoder']=='beamsearch'
    assert lines[0]['text']=='new' and lines[0]['retried']
    assert lines[1]['text']=='stable' and not lines[1]['retried']
    assert lines[3]['text']=='edge' and not lines[3]['retried']
    assert result['retries']==5


def test_pipeline_refines_only_after_orientation_selection(monkeypatch):
    page=Image.new('RGB',(20,30),'white')
    page.info['preprocessing']={}
    monkeypatch.setattr(pipeline,'read_pages',lambda *_:[page])
    monkeypatch.setattr(pipeline,'rectify_page',lambda image,**_:image)
    monkeypatch.setattr(pipeline,'flatten_lighting',lambda image:(image,{}))
    calls=[]
    def recognize(images,**kwargs):
        calls.append(kwargs['retry'])
        return {'lines':[line('discarded',.2)],'seconds':0.,'retries':0}
    monkeypatch.setattr(pipeline,'recognize',recognize)
    def recover(pages,ocr_pages,result,reader,expected_type):
        reader(ocr_pages)
        result['lines']=[line('selected',.4)]
        return {'attempts':1}
    monkeypatch.setattr(orientation,'recover',recover)
    refined=[]
    monkeypatch.setattr(pipeline,'refine_uncertain',lambda pages,result,*_:refined.append(result['lines'][0]['text']))
    monkeypatch.setattr(pipeline,'extract',lambda *_:{})
    monkeypatch.setattr(pipeline,'classify',lambda *_:{})
    pipeline.analyze(b'x','test.png','study',retry=True,finetuned=False)
    assert calls==[False,False]
    assert refined==['selected']
