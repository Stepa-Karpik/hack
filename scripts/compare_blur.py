"""Rejected OCR preprocessing candidates on two heavily blurred synthetic cases."""
from pathlib import Path
import sys,io,json
import cv2,numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT as root
from dekanat.pipeline import analyze
from dekanat.photo_augment import conditions
from dekanat.extraction import normalize


def main():
    rows=[]
    for name in ['defocus_2_2','motion_blur_9']:
        im=conditions()[name](Image.open(root/'data/demo/study.png').convert('RGB'))
        gray=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2GRAY)
        smooth=cv2.GaussianBlur(gray,(0,0),2)
        for method,array in [('unsharp_2',cv2.addWeighted(gray,3,smooth,-2,0)),('unsharp_4',cv2.addWeighted(gray,5,smooth,-4,0)),('otsu',cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]),('adaptive',cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,12))]:
            buf=io.BytesIO();Image.fromarray(array).save(buf,format='PNG')
            _,r=analyze(buf.getvalue(),'try.png','study',retry=False,photo=False)
            truth=json.loads((root/'data/demo/study.json').read_text(encoding='utf-8'))['fields']
            correct=sum(isinstance(v,str) and normalize(v)==normalize(str(r['fields'][k]['value'])) for k,v in truth.items())
            row={'case':name,'method':method,'correct':correct,'seconds':r['seconds']}
            rows.append(row);print(row,flush=True)
    (root/'artifacts/blur_candidates.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


if __name__=='__main__':main()
