"""Compose original fictional pages with annotated real signature crops.

Preserves original signature train/val separation. Val source is divided between
new val/test by sorted filename, never used for training. No field transcription
from original pages. This is composited development data, not real-page accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageOps
from scripts.unified.prepare_v2 import make, FONTS
from scripts.unified.contract import KEYS, parse


def signature_crop(image_path, label_path):
    boxes=[list(map(float,line.split())) for line in label_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not boxes:raise ValueError('No annotated signature')
    cls,x,y,w,h=boxes[0]
    if cls!=0 or not (0<x<1 and 0<y<1 and 0<w<=1 and 0<h<=1):
        raise ValueError('Invalid single-class signature source')
    with Image.open(image_path) as image:
        left=max(0,int((x-w/2)*image.width));top=max(0,int((y-h/2)*image.height))
        right=min(image.width,int((x+w/2)*image.width));bottom=min(image.height,int((y+h/2)*image.height))
        if right<=left or bottom<=top:raise ValueError('Empty source crop')
        crop=image.crop((left,top,right,bottom)).convert('L')
    return crop, [left,top,right,bottom]


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--font-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh immutable dataset directory')
    args.output.mkdir(parents=True)
    sources={s:sorted(f for f in (args.source/'images'/s).iterdir() if f.suffix.lower() in {'.jpg','.jpeg','.png'}
                    and (args.source/'labels'/s/(f.stem+'.txt')).exists()) for s in ['train','val']}
    manifest={'source':'Ultralytics signature boxes composited into original fictional pages',
              'source_url':'https://docs.ultralytics.com/datasets/detect/signature/',
              'license':'AGPL-3.0 per source documentation; local fonts not redistributed',
              'scope':'composited development, not original-page accuracy; real signatures already used by legacy detector',
              'source_split_preserved':True,'splits':{}}
    for split,items in [('train',sources['train']),('val',sources['val'][::2]),('test',sources['val'][1::2])]:
        directory=args.output/split;directory.mkdir();records=[]
        for i,file in enumerate(items):
            source_split='train' if split=='train' else 'val'
            label=args.source/'labels'/source_split/(file.stem+'.txt')
            crop,source_bbox=signature_crop(file,label)
            font=args.font_dir/FONTS[split][i%len(FONTS[split])]
            image,target=make(202610122+i+(0 if split=='train' else 100000 if split=='val' else 200000),
                              list(KEYS)[i%3],split,font,i%6,marks={'signature_present':False})
            # One quarter are explicit blank-caption controls; the crop is not pasted.
            positive=i%4!=0
            placed=None
            if positive:
                crop=ImageOps.autocontrast(crop)
                crop.thumbnail((300,82),Image.Resampling.LANCZOS)
                mask=ImageOps.invert(crop)
                ink=Image.new('RGB',crop.size,'#183d69')
                x,y=220,1330;image.paste(ink,(x,y),mask)
                placed=[round(x/1100*1000),round(y/1480*1000),
                        round((x+crop.width)/1100*1000),round((y+crop.height)/1480*1000)]
                target['fields']['signature_present']=True
                target['boxes']['signature_present']=placed
            parse(json.dumps(target))
            output=directory/f'{i:04d}.png';image.save(output)
            records.append({'image':output.relative_to(args.output).as_posix(),
                'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'target':target,
                'source_image':file.name,'source_split':source_split,
                'source_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                'source_label_sha256':hashlib.sha256(label.read_bytes()).hexdigest(),
                'source_bbox':source_bbox,'crop_pasted':positive,'font':font.name,
                'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest()})
        output=args.output/f'{split}.jsonl'
        output.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records),encoding='utf-8')
        manifest['splits'][split]={'count':len(records),'records_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                                 'source_split':'train' if split=='train' else 'val',
                                 'positive':sum(r['crop_pasted'] for r in records)}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':main()
