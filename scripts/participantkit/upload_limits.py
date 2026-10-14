"""Header-only preflight in the single worker, before OCR/model loading."""
import math
from io import BytesIO
from PIL import Image

MAX_IMAGE_PIXELS=24_000_000
MAX_PDF_PAGES=10
MAX_PDF_PIXELS=60_000_000


def inspect_upload(data,filename):
    if filename.lower().endswith('.pdf'):
        import pypdfium2 as pdf
        document=pdf.PdfDocument(data)
        total=0
        try:
            if not 1<=len(document)<=MAX_PDF_PAGES:raise ValueError('PDF page limit')
            for index in range(len(document)):
                page=document[index]
                try:width,height=page.get_size()
                finally:page.close()
                if not all(math.isfinite(v) and v>0 for v in (width,height)):
                    raise ValueError('Invalid PDF dimensions')
                scale=min(2.0,2400/max(width,height))
                total+=math.ceil(width*scale)*math.ceil(height*scale)
                if total>MAX_PDF_PIXELS:raise ValueError('PDF raster budget')
            return {'pages':len(document),'estimated_render_pixels':total}
        finally:document.close()
    with Image.open(BytesIO(data)) as image:
        if image.format not in {'PNG','JPEG'}:raise ValueError('Unsupported image format')
        if getattr(image,'n_frames',1)!=1:raise ValueError('Single-frame image required')
        width,height=image.size
        if width<=0 or height<=0 or width*height>MAX_IMAGE_PIXELS:
            raise ValueError('Image pixel limit')
        return {'pages':1,'image_pixels':width*height}
