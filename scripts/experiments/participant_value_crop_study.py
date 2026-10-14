from pathlib import Path
import sys,json,re,time
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from dekanat.io import read_pages
from dekanat.preprocessing import rectify_page
from dekanat.ocr import get_reader,quote_state
from format_v1 import LABELS,MISSING
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--kit',type=Path,required=True);kit=parser.parse_args().kit
manifest=json.loads((kit/'documents.json').read_text(encoding='utf-8'))
readers={'quote':get_reader(True,quote_state(),False),'base':get_reader(True,False,False),'numeric':get_reader(True,'candidate',False)}
rows=[]
for variant in ['image','pdf']:
 audits=json.loads((ROOT/f'artifacts/participant_marks_v5_{variant}_full.audit.json').read_text(encoding='utf-8'))['rows']
 outputs=json.loads((ROOT/f'artifacts/participant_marks_v5_{variant}_full.json').read_text(encoding='utf-8'))['documents']
 for record,prior,out in zip(manifest,audits,outputs):
  targets=[]
  for key in ['university','organization','document_number']:
   if out['fields'].get(key,MISSING)==MISSING:continue
   for line in prior['analysis']['ocr']['lines']:
    if re.match('^'+re.escape(LABELS[key])+r'\s*:',line['text'],re.I):targets.append((key,line))
  if not targets:continue
  path=kit/record[variant];pages=[rectify_page(p,photo=True) for p in read_pages(path.read_bytes(),path.name)]
  for key,line in targets:
   page=pages[line['page']];x1,y1,x2,y2=map(int,line['bbox']);full=cv2.cvtColor(np.asarray(page)[max(0,y1-5):y2+5,max(0,x1-5):min(page.width,x2+20)],cv2.COLOR_RGB2GRAY)
   mask=(full<150).astype('uint8');n,labels,stats,centroids=cv2.connectedComponentsWithStats(mask,8)
   dots=[(s,c) for s,c in zip(stats[1:],centroids[1:]) if 1<=s[4]<=max(16,full.shape[0]**2*.035) and s[2]<=max(5,full.shape[0]*.16) and s[3]<=max(5,full.shape[0]*.16)]
   pairs=[]
   for s,c in dots:
    for t,d in dots:
     if .12*full.shape[0]<d[1]-c[1]<.5*full.shape[0] and abs(c[0]-d[0])<=2 and .5<= s[4]/max(t[4],1)<=2.1:pairs.append(int(max(s[0]+s[2],t[0]+t[2])))
   # First punctuation pair at a plausible label position; no expected names.
   cuts=sorted(set(x for x in pairs if full.shape[1]*.10<x<full.shape[1]*.70))
   predictions={}
   for cut in cuts[:3]:
    crop=full[:,max(0,cut+1):]
    predictions[str(cut)]={name:[[str(p[1]),float(p[2])] for p in reader.recognize(crop,detail=1,decoder='greedy',batch_size=1)] for name,reader in readers.items()}
   rows.append({'variant':variant,'document_id':record['document_id'],'key':key,'before':out['fields'][key],'label_text':line['text'],'bbox':line['bbox'],'colon_cuts':cuts,'predictions':predictions})
   print(variant,record['document_id'],key,predictions,flush=True)
report={'scope':'Viewed development-only value-crop diagnostic; three previous local readers; no references or training; colon component heuristic not deployed.','rows':rows}
target=ROOT/'artifacts/participant_value_crop_study_v2.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
