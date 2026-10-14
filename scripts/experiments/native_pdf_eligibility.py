"""Conservative offline native-PDF eligibility. Not imported by app/runtime.

This checks visible text availability, not text authenticity or correct Unicode
mapping. Ineligible documents must use raster OCR; eligibility never proves FIO.
"""
import ctypes,math
import numpy as np
import pypdfium2 as pdf


def inspect_native_pdf(data):
    doc=pdf.PdfDocument(data);pages=[]
    try:
        if not 1<=len(doc)<=10:return {'eligible':False,'reason':'page_count','pages':[]}
        for index in range(len(doc)):
            page=doc[index];textpage=None;bitmap=None
            try:
                width,height=page.get_size()
                if page.get_rotation()!=0:return {'eligible':False,'reason':'rotation','pages':pages}
                box=page.get_bbox()
                if any(abs(a-b)>.1 for a,b in zip(box,(0,0,width,height))):return {'eligible':False,'reason':'nonzero_page_origin','pages':pages}
                textpage=page.get_textpage();count=textpage.count_chars()
                if not 40<=count<=30000:return {'eligible':False,'reason':'text_count','pages':pages}
                text=textpage.get_text_range()
                if '\ufffd' in text or '\x00' in text:return {'eligible':False,'reason':'unicode_mapping','pages':pages}
                n_objects=0
                for obj in page.get_objects(max_depth=15):
                    n_objects+=1
                    if n_objects>4096:return {'eligible':False,'reason':'object_count','pages':pages}
                    if obj.type==pdf.raw.FPDF_PAGEOBJ_IMAGE:
                        left,bottom,right,top=obj.get_bounds()
                        if (right-left)*(top-bottom)>.2*width*height:return {'eligible':False,'reason':'dominant_raster','pages':pages}
                    if obj.type==pdf.raw.FPDF_PAGEOBJ_TEXT:
                        if pdf.raw.FPDFTextObj_GetTextRenderMode(obj.raw)!=0:return {'eligible':False,'reason':'unsupported_text_render_mode','pages':pages}
                        color=[ctypes.c_uint() for _ in range(4)]
                        if not pdf.raw.FPDFPageObj_GetFillColor(obj.raw,*[ctypes.byref(c) for c in color]):return {'eligible':False,'reason':'unreadable_color','pages':pages}
                        red,green,blue,alpha=[c.value for c in color]
                        if alpha<250 or .2126*red+.7152*green+.0722*blue>220:return {'eligible':False,'reason':'invisible_or_pale_text','pages':pages}
                scale=min(2.,2400/max(width,height));bitmap=page.render(scale=scale)
                image=np.asarray(bitmap.to_pil().convert('L'))
                ratios=[]
                # At most 240 evenly spaced glyphs; resource limit and no OCR model call.
                stride=max(1,count//240)
                for n in range(0,count,stride):
                    char=textpage.get_text_range(n,1)
                    if not char or char.isspace():continue
                    left,bottom,right,top=textpage.get_charbox(n)
                    coords=[left*scale,(height-top)*scale,right*scale,(height-bottom)*scale]
                    if not all(math.isfinite(x) for x in coords):return {'eligible':False,'reason':'nonfinite_glyph_geometry','pages':pages}
                    x1,y1,x2,y2=coords
                    if x1<-.5 or y1<-.5 or x2>image.shape[1]+.5 or y2>image.shape[0]+.5 or x2<=x1 or y2<=y1:return {'eligible':False,'reason':'out_of_bounds_glyph','pages':pages}
                    crop=image[max(0,math.floor(y1)):min(image.shape[0],math.ceil(y2)),max(0,math.floor(x1)):min(image.shape[1],math.ceil(x2))]
                    if crop.size:ratios.append(float(np.mean(crop<220)))
                if len(ratios)<20 or sum(r>.02 for r in ratios)/len(ratios)<.95:return {'eligible':False,'reason':'glyphs_not_visibly_rendered','pages':pages}
                pages.append({'page':index,'chars':count,'objects':n_objects,'sampled_glyphs':len(ratios),'visible_fraction':sum(r>.02 for r in ratios)/len(ratios)})
            finally:
                if bitmap:bitmap.close()
                if textpage:textpage.close()
                page.close()
    finally:doc.close()
    return {'eligible':True,'reason':None,'pages':pages,'scope':'Visible-layer heuristics only; no calibrated confidence, semantic correctness or authenticity proof'}
