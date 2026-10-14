from pathlib import Path
import sys,json,hashlib,re,time
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from dekanat.ocr import get_reader,quote_state
from dekanat.io import read_pages
from dekanat.preprocessing import rectify_page
from format_v1 import MONTHS,DATE,iso,MISSING,LABELS
from labeled_fields import extract_contract
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--kit',type=Path,required=True);kit=parser.parse_args().kit
config=json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))
manifest=json.loads((kit/'documents.json').read_text(encoding='utf-8'))
reader=get_reader(True,False,detector=False);quote=get_reader(True,quote_state(),detector=False)
rows=[];started=time.perf_counter()
for variant in ['image','pdf']:
 raw=json.loads((ROOT/f'artifacts/participant_labels_v3_{variant}_full.audit.json').read_text(encoding='utf-8'))['rows']
 for record,prior in zip(manifest,raw):
  analysis=prior['analysis'];fields,evidence=extract_contract(analysis,record['document_type'],config)
  targets=[]
  for key,e in evidence.items():
   if e.get('status')=='conflict':continue
   if key in ['university','organization']:
    targets.append((key,e))
   elif fields[key]==MISSING and re.search(r'(?:'+ '|'.join(MONTHS)+r')\s+\d{4}',e.get('literal',''),re.I):targets.append((key,e))
  if not targets:continue
  path=kit/record[variant];pages=[rectify_page(p,photo=True) for p in read_pages(path.read_bytes(),path.name)]
  for key,e in targets:
   parts=e.get('parts') or e.get('proposals',[{}])[0].get('parts',[])
   if not parts:continue
   page=parts[0]['page'];boxes=[p['bbox'] for p in parts]
   x1=max(0,int(min(b[0] for b in boxes))-10);y1=max(0,int(min(b[1] for b in boxes))-8)
   x2=min(pages[page].width,int(max(b[2] for b in boxes))+16);y2=min(pages[page].height,int(max(b[3] for b in boxes))+8)
   crop=cv2.cvtColor(np.asarray(pages[page])[y1:y2,x1:x2],cv2.COLOR_RGB2GRAY)
   predictions=[]
   for scale in [1,2]:
    image=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC) if scale!=1 else crop
    model=quote if key in ['university','organization'] else reader
    out=model.recognize(image,detail=1,decoder='greedy',batch_size=1)
    predictions.append([[str(p[1]),float(p[2])] for p in out])
   rows.append({'variant':variant,'document_id':record['document_id'],'key':key,'before':fields[key],'literal':e.get('literal'),'bbox':[x1,y1,x2,y2],'page':page,'predictions':predictions})
   print(variant,record['document_id'],key,predictions,flush=True)
report={'scope':'Viewed development crop study only; references not loaded, no deployment/weight change. Full row crops, gray native/2x cubic, greedy existing base for dates and selected guillemet weights for names.','seconds':time.perf_counter()-started,'rows':rows}
path=ROOT/'artifacts/participant_crop_study_v1.json';assert not path.exists();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
