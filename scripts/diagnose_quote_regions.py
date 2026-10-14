"""Reproduce single/two-row quote probes from frozen viewed study reports."""
import hashlib,json,sys,time
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dekanat.io import read_pages
from dekanat.preprocessing import rectify_page,flatten_lighting
from dekanat.extraction import merge_rows
from dekanat.ocr import get_reader


def main():
    baseline=json.loads((ROOT/'artifacts/realistic_documents_before_headers.json').read_text(encoding='utf-8'))
    reader=get_reader(True,ROOT/'models/ocr_quotes.pt',detector=False)
    results=[]
    for record in baseline['rows'][:2]:
        path=ROOT.parent/'Реалистичные-документы'/record['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
        arr=np.asarray(flatten_lighting(rectify_page(read_pages(path.read_bytes(),path.name)[0]))[0])
        rows=merge_rows(record['analysis']['ocr']['lines'])
        for index,row in enumerate(rows):
            if not ('университет' in row['text'].lower() and row['bbox'][1]<700):continue
            for count in [1,2]:
                parts=rows[index:index+count]
                x1=min(x['bbox'][0] for x in parts);x2=max(x['bbox'][2] for x in parts)
                y1=min(x['bbox'][1] for x in parts);y2=max(x['bbox'][3] for x in parts)
                crop=arr[max(0,int(y1)-4):int(y2)+4,max(0,int(x1)-4):int(x2)+4]
                gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY);start=time.perf_counter()
                reading=reader.recognize(gray,decoder='greedy',detail=1,batch_size=1)
                results.append({'file':path.name,'source_sha256':record['sha256'],'parts':parts,
                                'crop_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),'rows':count,
                                'reading':[(text,float(conf)) for _,text,conf in reading],'seconds':time.perf_counter()-start})
                print(path.name,count,results[-1]['reading'],flush=True)
    report={'scope':'Actual local quote recognizer diagnostic on eight viewed crops from two own study PDFs. No runtime change, same weights, not independent quality. Two-row crop is diagnostic and can concatenate adjacent unrelated content.',
            'weights_sha256':hashlib.sha256((ROOT/'models/ocr_quotes.pt').read_bytes()).hexdigest(),
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'rows':results}
    (ROOT/'artifacts/quote_region_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
