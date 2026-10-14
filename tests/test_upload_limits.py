from io import BytesIO
import time
import pytest
from PIL import Image
import pypdfium2 as pdf
from scripts.participantkit.upload_limits import inspect_upload
from scripts.participantkit.http_api import JobStore


def image_bytes(size=(120,180),fmt='PNG'):
    output=BytesIO();Image.new('RGB',size,'white').save(output,format=fmt);return output.getvalue()


def pdf_bytes(count=1,width=595,height=842):
    document=pdf.PdfDocument.new();output=BytesIO()
    try:
        for _ in range(count):
            page=document.new_page(width,height);page.close()
        document.save(output);return output.getvalue()
    finally:document.close()


@pytest.mark.parametrize('fmt',['PNG','JPEG'])
def test_regular_image(fmt):
    assert inspect_upload(image_bytes(fmt=fmt),'image.'+fmt.lower())['image_pixels']==21600


def test_large_compressed_image_rejected_before_decode():
    data=image_bytes((5000,5000))
    assert len(data)<100000
    with pytest.raises(ValueError,match='pixel limit'):inspect_upload(data,'large.png')


def test_other_content_and_multiframe_rejected():
    with pytest.raises(Exception):inspect_upload(b'not an image','a.png')
    with pytest.raises(ValueError,match='format'):inspect_upload(image_bytes(fmt='GIF'),'a.png')
    output=BytesIO();Image.new('RGB',(20,20),'white').save(output,format='PNG',save_all=True,append_images=[Image.new('RGB',(20,20),'black')])
    with pytest.raises(ValueError,match='frame'):inspect_upload(output.getvalue(),'a.png')


def test_pdf_regular_ten_pages_and_huge_page_use_render_budget():
    assert inspect_upload(pdf_bytes(10),'ten.pdf')['pages']==10
    assert inspect_upload(pdf_bytes(1,100000,100000),'huge.pdf')['estimated_render_pixels']==2400**2
    with pytest.raises(ValueError,match='page limit'):inspect_upload(pdf_bytes(11),'eleven.pdf')


def test_invalid_upload_never_calls_inference_and_next_one_runs():
    import base64
    calls=[]
    def infer(*args,**kwargs):calls.append(1);return {'audit':{'status':'uncertain','semantic_confidence':None}}
    store=JobStore(infer)
    def submit(data):return store.submit({'filename':'a.png','document_type':'study_certificate','questions':[],'data_base64':base64.b64encode(data).decode()})
    def wait(key):
        end=time.monotonic()+3
        while time.monotonic()<end:
            value=store.get(key)
            if value['status'] in {'done','failed'}:return value
            time.sleep(.01)
        raise AssertionError('worker stalled')
    try:
        assert wait(submit(b'bad'))['status']=='failed';assert calls==[]
        value=wait(submit(image_bytes()))
        assert value['response']['audit']=={'status':'uncertain','semantic_confidence':None}
        assert len(calls)==1
    finally:store.close()
