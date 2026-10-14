"""Prototype only: native glyph geometry converted into OCR-compatible rows."""
import math
from pathlib import Path
import pypdfium2 as pdf


def native_lines(data):
    document=pdf.PdfDocument(data);lines=[]
    try:
        for page_index in range(len(document)):
            page=document[page_index];width,height=page.get_size();scale=min(2.0,2400/max(width,height))
            if page.get_rotation()!=0:page.close();return None
            textpage=page.get_textpage();parts=[]
            def flush():
                nonlocal parts
                content=''.join(c for c,_ in parts).strip()
                boxes=[box for c,box in parts if not c.isspace()]
                if content and boxes:
                    lines.append({'text':content,'page':page_index,'confidence':1.0,
                                  'bbox':[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
                                  'method':'native_pdf_text_prototype'})
                parts=[]
            try:
                for index in range(textpage.count_chars()):
                    char=textpage.get_text_range(index,1)
                    if char in {'\r','\n'}:flush();continue
                    if not char or char=='\x00':continue
                    left,bottom,right,top=textpage.get_charbox(index)
                    if not all(math.isfinite(v) for v in [left,bottom,right,top]):return None
                    parts.append((char,[left*scale,(height-top)*scale,right*scale,(height-bottom)*scale]))
                flush()
            finally:textpage.close();page.close()
    finally:document.close()
    return lines


