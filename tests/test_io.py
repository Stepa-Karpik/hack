from io import BytesIO
from PIL import Image
from dekanat.io import read_pages

def test_image_decode():
    buffer=BytesIO();Image.new("RGB",(120,160),"white").save(buffer,format="PNG")
    pages=read_pages(buffer.getvalue(),"test.png")
    assert len(pages)==1 and pages[0].size==(120,160)

def test_pdf_render_in_memory():
    buffer=BytesIO();Image.new("RGB",(120,160),"white").save(buffer,format="PDF")
    pages=read_pages(buffer.getvalue(),"test.pdf")
    assert len(pages)==1 and pages[0].mode=="RGB"

