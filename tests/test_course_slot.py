from PIL import Image,ImageDraw
from dekanat import ocr
from dekanat.extraction import extract


def context():
    return [{'text':'от студента(тки)','bbox':[10,10,110,30],'page':0,'confidence':.8},
            {'text':'курса','bbox':[150,10,190,30],'page':0,'confidence':.9}]


def page(ink=True):
    image=Image.new('RGB',(200,50),'white');draw=ImageDraw.Draw(image)
    draw.line((112,29,148,29),fill='black')
    if ink:draw.rectangle((124,12,129,25),fill='black')
    return image


class Reader:
    def __init__(self,text='2',confidence=.99):self.text=text;self.confidence=confidence;self.calls=0
    def recognize(self,*args,**kwargs):
        self.calls+=1;return [(None,self.text,self.confidence)]


def test_recover_missing_digit_in_bounded_student_slot(monkeypatch):
    reader=Reader();monkeypatch.setattr(ocr,'get_reader',lambda *a,**k:reader)
    lines=context();result=ocr.recover_course([page()],lines)
    assert result['text']=='2' and result['confidence']==.8
    assert result['bbox'][0]>=112 and result['bbox'][2]<150
    assert extract(lines+[result],'leave')['course']['value']=='2'


def test_empty_underlined_slot_never_calls_recognizer(monkeypatch):
    reader=Reader();monkeypatch.setattr(ocr,'get_reader',lambda *a,**k:reader)
    assert ocr.recover_course([page(False)],context()) is None and reader.calls==0


def test_wrong_page_label_rejected(monkeypatch):
    reader=Reader();monkeypatch.setattr(ocr,'get_reader',lambda *a,**k:reader)
    lines=context();lines[1]['page']=1
    assert ocr.recover_course([page()],lines) is None and reader.calls==0


def test_weak_numeric_reading_rejected(monkeypatch):
    monkeypatch.setattr(ocr,'get_reader',lambda *a,**k:Reader(confidence=.4))
    assert ocr.recover_course([page()],context()) is None


def test_moderate_numeric_reading_requires_review(monkeypatch):
    monkeypatch.setattr(ocr,'get_reader',lambda *a,**k:Reader(confidence=.7))
    result=ocr.recover_course([page()],context())
    assert result['text']=='2' and result['requires_review'] is True and result['confidence']==.7
