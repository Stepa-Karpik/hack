"""Original synthetic camera controls with exact projective label transformation."""
import argparse
import copy
import hashlib
import json
import math
import random
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from scripts.unified.contract import parse, KEYS
from scripts.unified.prepare_v2 import make, FONTS


def homography(source, destination):
    a=[]; b=[]
    for (x,y),(u,v) in zip(source,destination):
        a.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        b.extend([u,v])
    return np.append(np.linalg.solve(np.array(a,float),np.array(b,float)),1).reshape(3,3)


def point(matrix, x, y):
    out=matrix @ np.array([x,y,1.])
    if not np.isfinite(out).all() or abs(out[2])<1e-8:raise ValueError('Invalid projective point')
    return out[:2]/out[2]


def transform(image,target,destination):
    w,h=image.size
    matrix=homography([(0,0),(w,0),(w,h),(0,h)],destination)
    # Pillow samples destination -> source; labels use source -> destination.
    inverse=np.linalg.inv(matrix);inverse/=inverse[2,2]
    result=image.transform(image.size,Image.Transform.PERSPECTIVE,tuple(inverse.flatten()[:8]),
                           resample=Image.Resampling.BICUBIC,fillcolor='#333538')
    value=copy.deepcopy(target)
    for key,box in target['boxes'].items():
        if box is None:continue
        x1,y1,x2,y2=box
        corners=[point(matrix,x*w/1000,y*h/1000) for x,y in [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]]
        xs=[p[0]*1000/w for p in corners];ys=[p[1]*1000/h for p in corners]
        bounds=[math.floor(min(xs)),math.floor(min(ys)),math.ceil(max(xs)),math.ceil(max(ys))]
        if bounds[0]<0 or bounds[1]<0 or bounds[2]>1000 or bounds[3]>1000:
            raise ValueError('Transformed field outside frame; never clamp annotations')
        value['boxes'][key]=bounds
    parse(json.dumps(value))
    return result,value,matrix.tolist()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--font-dir',type=Path,required=True);p.add_argument('--train',type=int,default=120)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Fresh dataset directory required')
    args.output.mkdir(parents=True)
    manifest={'source':'original expanded renderer, new seeds, projective resampling',
        'license':'AGPL-3.0 project code; font binaries not redistributed',
        'scope':'synthetic development, shared renderer/content pools with expanded v2; not independent real documents',
        'seed':202630124,'splits':{},'transform':'four-corner homography, inverse image sampling, forward enclosing boxes; no clipping'}
    for split,count,offset in [('train',args.train,0),('val',12,100000),('test',12,200000)]:
        (args.output/split).mkdir();rows=[]
        for i in range(count):
            seed=202630124+offset+i;rng=random.Random(seed)
            font=args.font_dir/FONTS[split][i%len(FONTS[split])]
            image,target=make(seed,list(KEYS)[i%3],split,font,i%6,
                empty_keys=('student_name',) if i%7==0 else ())
            w,h=image.size
            # A smaller page in the frame simulates lower character pixel density.
            scale=rng.uniform(.60,.94);mx=w*(1-scale)/2;my=h*(1-scale)/2
            dx=w*rng.uniform(.015,.055);dy=h*rng.uniform(.015,.055)
            mode=i%4
            dest=[(mx,my),(w-mx,my),(w-mx,h-my),(mx,h-my)]
            if mode==0:dest=[(mx+dx,my),(w-mx-dx,my),(w-mx,h-my),(mx,h-my)]
            elif mode==1:dest=[(mx,my),(w-mx,my),(w-mx-dx,h-my),(mx+dx,h-my)]
            elif mode==2:dest=[(mx,my+dy),(w-mx,my),(w-mx,h-my),(mx,h-my-dy)]
            else:dest=[(mx,my),(w-mx,my+dy),(w-mx,h-my-dy),(mx,h-my)]
            image,target,matrix=transform(image,target,dest)
            contrast=rng.uniform(.68,1.05);blur=rng.uniform(0,.65)
            image=ImageEnhance.Contrast(image).enhance(contrast).filter(ImageFilter.GaussianBlur(blur))
            file=args.output/split/f'{i:04d}.png';image.save(file)
            rows.append({'image':file.relative_to(args.output).as_posix(),'target':target,
                'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'seed':seed,
                'font':font.name,'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),
                'camera':{'scale':scale,'mode':mode,'destination':dest,'homography':matrix,'contrast':contrast,'blur':blur}})
        file=args.output/f'{split}.jsonl';file.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
        manifest['splits'][split]={'count':count,'records_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'fonts':FONTS[split]}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest))


if __name__=='__main__':main()
