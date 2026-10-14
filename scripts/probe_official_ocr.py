"""Offline recognizer probe on already viewed development crops; no deployment."""
import argparse,hashlib,json,re,sys
from pathlib import Path
import cv2,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from dekanat.io import read_pages
from dekanat.ocr import get_reader


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--weights',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();reader=get_reader(True,args.weights,detector=False)
    truth=json.loads((ROOT/'artifacts/official_evaluation_truth.json').read_text(encoding='utf-8'))
    sources={r['id']:r for r in truth['records']}
    development=json.loads((ROOT/'artifacts/official_development_v15_quotes.json').read_text(encoding='utf-8'))
    rows=[]
    for record in development['rows']:
        if not record['id'].startswith(('hse_family_filled','rudn_character_filled')):continue
        source=sources[record['id']];path=Path(source['input']);data=path.read_bytes()
        assert hashlib.sha256(data).hexdigest()==source['sha256']
        pages=read_pages(data,path.name)
        for line in record['analysis']['ocr']['lines']:
            text=line['text']
            target=bool(re.search(r'практику\s+в\b|заслуживает\s+оценки',text,re.IGNORECASE))
            # For diagnostic-only caption probes use existing position near the
            # bottom; this is not a runtime label inferred from expected text.
            caption=record['id'].startswith('hse') and len(text.strip())<35 and text.strip().endswith(')') and line['bbox'][1]>pages[line['page']].height*.4
            if not(target or caption):continue
            x1,y1,x2,y2=map(int,line['bbox']);page=np.asarray(pages[line['page']]);crop=page[max(0,y1-4):y2+4,max(0,x1-4):x2+4]
            if not crop.size:continue
            image=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
            reading=reader.recognize(image,decoder='greedy',batch_size=1,detail=1)
            rows.append({'document':record['id'],'baseline':text,'bbox':line['bbox'],'page':line['page'],
                         'prediction':reading[0][1] if reading else None,'confidence':float(reading[0][2]) if reading else 0})
    args.report.write_text(json.dumps({'scope':'Viewed development crop diagnostic, no weight deployment, confidence is not calibrated correctness, no expected-value restoration. Coordinates derived from preserved baseline OCR; not an independent evaluation.',
                                      'candidate_sha256':hashlib.sha256(args.weights.read_bytes()).hexdigest(),'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows:print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
