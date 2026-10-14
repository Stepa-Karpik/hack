from pathlib import Path
import json,hashlib
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from PIL import Image,ImageDraw,ImageFont
BASE=Path('work/official-expansion-v1/native-controls');BASE.mkdir(parents=True,exist_ok=True)
font=Path('C:/Windows/Fonts/arial.ttf');pdfmetrics.registerFont(TTFont('LocalArial',str(font)))
text=['Справка об обучении. ФИО студента: Семёнов Павел Антонович.',
      'Организация: ООО «Учебный пример». Дата: 11.10.2026.',
      'Собственный диагностический документ, без подписи и печати.']
im=Image.new('RGB',(595,842),'white');draw=ImageDraw.Draw(im)
for i,line in enumerate(text):draw.text((50,142+i*30),line,font=ImageFont.truetype(str(font),12),fill='black')
rows=[]
for kind in ['visible','white_text','invisible_text','occluded','rotation','raster_only','dominant_raster','small_logo']:
    path=BASE/(kind+'.pdf');c=canvas.Canvas(str(path),pagesize=(595,842));c.setFont('LocalArial',12)
    if kind=='rotation':c.setPageRotation(90)
    if kind in {'raster_only','dominant_raster'}:c.drawImage(ImageReader(im),0,0,595,842)
    if kind=='white_text':c.setFillColorRGB(1,1,1)
    if kind=='invisible_text':
        t=c.beginText(50,700);t.setFont('LocalArial',12);t.setTextRenderMode(3)
        for line in text:t.textLine(line)
        c.drawText(t)
    elif kind!='raster_only':
        for i,line in enumerate(text):c.drawString(50,700-i*30,line)
    if kind=='occluded':c.setFillColorRGB(1,1,1);c.rect(0,550,595,250,fill=1,stroke=0)
    if kind=='small_logo':c.drawImage(ImageReader(Image.new('RGB',(20,20),'navy')),550,780,20,20)
    c.save()
    rows.append({'id':kind,'input':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'expected_eligible':kind in {'visible','small_logo'}})
report={'scope':'Eight own synthetic PDF visibility controls, created for eligibility diagnosis; not an OCR benchmark, no external documents or model training. Local font Arial used and not distributed.',
        'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),'records':rows}
(BASE/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(BASE/'manifest.json')
