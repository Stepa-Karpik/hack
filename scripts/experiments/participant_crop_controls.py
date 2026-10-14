from pathlib import Path
import sys,json,hashlib,time
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from crop_recovery import recover
from format_v1 import MISSING
cases=[('Дата заявления: 17 мая 2025 года','мая 2025 года','2025-05-17'),('Дата заявления: 2 декабря 2028 года','декабря 2028 года','2028-12-02'),('Дата заявления: 29 февраля 2028 года','февраля 2028 года','2028-02-29'),('Дата заявления: 31 февраля 2025 года','февраля 2025 года',MISSING),('Дата заявления: мая 2025 года','мая 2025 года',MISSING),('Дата заявления:','',MISSING)]
rows=[]
for fontname in ['arial.ttf','times.ttf']:
 fontpath=Path('C:/Windows/Fonts')/fontname
 font=ImageFont.truetype(str(fontpath),28)
 for i,(text,literal,truth) in enumerate(cases):
  image=Image.new('RGB',(1000,100),'white');draw=ImageDraw.Draw(image);draw.text((20,25),text,font=font,fill='black');box=list(draw.textbbox((20,25),text,font=font))
  fields={'application_date':MISSING};e={'application_date':{'literal':literal,'status':'not_found','parts':[{'text':'Дата заявления: '+literal,'page':0,'bbox':box,'confidence':.9}]}}
  result=recover([image],fields,e)
  rows.append({'font':fontname,'font_sha256':hashlib.sha256(fontpath.read_bytes()).hexdigest(),'printed':text,'initial_suffix':literal,'expected':truth,'actual':fields['application_date'],'correct':truth==fields['application_date'],'audit':result})
  print(fontname,i,truth,fields['application_date'],flush=True)
report={'scope':'12 new synthetic crop controls, two installed Windows fonts not distributed; standalone recovery only, not full-app/real accuracy or independent target benchmark. No training or reference-kit lookup.','rows':rows,'correct':sum(r['correct'] for r in rows),'new_wrong_nonempty':sum(r['actual']!=MISSING and not r['correct'] for r in rows)}
target=ROOT/'artifacts/participant_crop_controls_v4.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
