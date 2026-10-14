from io import BytesIO
from PIL import Image, ImageOps
import numpy as np

def read_pages(data: bytes, filename: str):
    if filename.lower().endswith(".pdf"):
        import pypdfium2 as pdf
        document = pdf.PdfDocument(data)
        if len(document) > 10:
            document.close()
            raise ValueError("Для прототипа допустимо не более 10 страниц PDF.")
        pages = []
        try:
            for i in range(len(document)):
                page = document[i]
                # Limit rendering before allocation, retaining enough detail for OCR.
                scale = min(2.0, 2400 / max(page.get_size()))
                bitmap = page.render(scale=scale)
                pages.append(bitmap.to_pil().convert("RGB").copy())
                bitmap.close()
                page.close()
        finally:
            document.close()
        return pages
    with Image.open(BytesIO(data)) as image:
        return [ImageOps.exif_transpose(image).convert("RGB").copy()]

def prepare(image, max_side=2000):
    import cv2
    original = np.asarray(image)
    h, w = original.shape[:2]
    scale = min(1, max_side / max(h, w))
    resized = cv2.resize(original, (round(w * scale), round(h * scale))) if scale < 1 else original.copy()
    return resized, scale

