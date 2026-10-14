"""Offline candidate, deliberately not imported by service or HTTP."""
import argparse,json,re,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.ocr import get_reader,quote_state
from scripts.participantkit.labeled_fields import label_match,_box
from scripts.participantkit.crop_recovery import quoted
from scripts.participantkit.format_v1 import norm


def propose(image,lines):
    starts=[p for p in lines if label_match(p.get('text','')) and label_match(p['text'])[0]=='university']
    if len(starts)!=1:return {'accepted':None,'reason':'unique_label_required'}
    start=starts[0];box=_box(start)
    if box is None:return {'accepted':None,'reason':'no_box'}
    height=box[3]-box[1];parts=[start];bottom=box[3]
    for _ in range(2):
        near=[p for p in lines if _box(p) and p.get('page',0)==start.get('page',0)
              and 0<=_box(p)[1]-bottom<=height*1.2 and abs(_box(p)[0]-box[0])<=height*2]
        near.sort(key=lambda p:_box(p)[1])
        if not near:break
        part=near[0]
        if label_match(part['text']) or ':' in part['text'] or re.search(r'макет|вымышлен|подпись|печать',part['text'],re.I):break
        parts.append(part);bottom=_box(part)[3]
    if len(parts)<2:return {'accepted':None,'reason':'no_wrapped_rows'}
    reader=get_reader(True,quote_state(),detector=False);variants=[]
    for scale in [1,2]:
        readings=[]
        for part in parts:
            x1,y1,x2,y2=_box(part)
            crop=np.asarray(image.crop((max(0,int(x1)-8),max(0,int(y1)-6),min(image.width,int(x2)+12),min(image.height,int(y2)+6))))
            gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
            if scale==2:gray=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
            items=reader.recognize(gray,detail=1,decoder='greedy',batch_size=1)
            readings.append([[str(p[1]),float(p[2])] for p in items])
        variants.append(readings)
    values=[]
    for readings in variants:
        if any(len(r)!=1 or r[0][1]<.5 for r in readings):break
        text=' '.join(r[0][0] for r in readings)
        prefix=re.match(r'^\s*Название вуза\s*[:«]\s*',text,re.I)
        value=text[prefix.end():].strip() if prefix else None
        if value and quoted(value):values.append(value)
    accepted=values[0] if len(values)==2 and norm(values[0])==norm(values[1]) else None
    return {'accepted':accepted,'parts':parts,'readings':variants,'semantic_confidence':None,'scope':'Correlated reads, not calibrated evidence; diagnostic only'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output)
    if output.exists():raise FileExistsError(output)
    source=json.loads(Path(args.input).read_text(encoding='utf-8'));rows=[]
    for item in source['rows']:
        image=Image.new('RGB',(1400,850),'white');draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('C:/Windows/Fonts/'+item['font'],28)
        for i,text in enumerate(item['printed']):draw.text((60,35+i*48),text,font=font,fill='black')
        proposal=propose(image,item['runtime']['ocr']['lines'])
        actual=proposal['accepted'] or item['actual']
        rows.append({'font':item['font'],'case':item['case'],'before':item['actual'],'expected':item['expected'],'after':actual,'exact':actual==item['expected'],'changed_wrong':actual!=item['actual'] and actual!=item['expected'],'proposal':proposal})
        print(item['font'],item['case'],proposal['accepted'] is not None,actual==item['expected'],flush=True)
    report={'scope':'Offline reread candidate on the same twelve viewed synthetic controls, no deployment or independent accuracy. Existing fields not changed in service.','rows':rows,'exact':sum(r['exact'] for r in rows),'changed_wrong':sum(r['changed_wrong'] for r in rows),'accepted':sum(r['proposal']['accepted'] is not None for r in rows),'total':len(rows)}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(report['exact'],report['accepted'],report['changed_wrong'])


if __name__=='__main__':main()
