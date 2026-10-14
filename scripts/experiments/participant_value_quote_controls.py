from pathlib import Path
import json,sys,hashlib
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from value_quote_recovery import recover
rows=[]
cases=[('organization','Название организации: Компания «Тихая роща»','Компания кТихая рощах','Компания «Тихая роща»'),('university','Название вуза: Университет «Кедр»','Университет кКедрх','Университет «Кедр»'),('organization','Название организации:','не найдено','не найдено'),('organization','Название организации: Компания Без кавычек','Компания Без кавычек','Компания Без кавычек')]
for fontname in ['arial.ttf','times.ttf']:
 path=Path('C:/Windows/Fonts')/fontname;font=ImageFont.truetype(str(path),28)
 for key,text,before,expected in cases:
  image=Image.new('RGB',(1000,100),'white');draw=ImageDraw.Draw(image);draw.text((20,25),text,font=font,fill='black');box=list(draw.textbbox((20,25),text,font=font))
  a={'ocr':{'lines':[{'text':text.replace('«','к').replace('»','х'),'bbox':box,'page':0,'confidence':.9}]}}
  fields={key:before};e={key:{'status':'uncertain'}};audit=recover([image],a,fields,e)
  rows.append({'font':fontname,'font_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'printed':text,'before':before,'expected':expected,'actual':fields[key],'correct':fields[key]==expected,'changed_to_wrong':fields[key]!=before and fields[key]!=expected,'audit':audit})
report={'scope':'Eight newly generated synthetic value quote controls, two local Windows fonts not distributed; standalone not real/full-app accuracy; no training.','rows':rows,'correct':sum(r['correct'] for r in rows),'total':len(rows),'changed_to_wrong':sum(r['changed_to_wrong'] for r in rows)}
out=ROOT/'artifacts/participant_value_quote_controls_v6.json';assert not out.exists();out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(report['correct'],report['total'],report['changed_to_wrong'])
