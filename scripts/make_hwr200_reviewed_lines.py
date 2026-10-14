"""Fixed literal line review made before any PARSeq predictions on these crops.

Coordinates refer to a 1000px-wide inspection view, mapped to original pixels.
These are evaluation-only; full-text dataset labels were not used as line labels.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

REVIEW = [
    (0, [24,8,798,81], 'Что главное в жизни: семья'),
    (0, [5,278,850,338], 'раскрытия поставленного вопроса'),
    (0, [0,580,850,647], 'работа или семья. В результате'),
    (1, [151,323,900,380], 'задумываемся над тем, что же ещё предоставляет'),
    (1, [150,383,953,435], 'оно помимо материальной выгоды... Именно поэтому'),
    (1, [148,498,902,554], 'проблему необходимости образования нравственного,'),
    (2, [22,309,900,365], 'знает сотни примеров, когда некоторые открытия'),
    (2, [25,437,868,489], 'ми, и стали признанными лишь после смерти'),
    (2, [34,605,908,674], 'Подтверждая эту мысль, он ссылается на историю'),
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    crops=args.target/'reviewed_lines';crops.mkdir(exist_ok=True)
    rows=[]
    sheet=Image.new('RGB',(1000,len(REVIEW)*130),'white')
    draw=ImageDraw.Draw(sheet)
    for index,(writer,box,text) in enumerate(REVIEW):
        source=args.target/f'writer_{writer}_scan.jpg'
        image=Image.open(source).convert('RGB')
        scale=image.width/1000
        original_box=[round(v*scale) for v in box]
        crop=image.crop(original_box)
        target=crops/f'writer_{writer}_line_{index}.png';crop.save(target)
        row={'id':f'hwr200_{index}','writer':writer,'split':'validation' if writer in [0,1] else 'test',
             'image':str(target),'text':text,'bbox':original_box,'approved':True,
             'document_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'crop_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
             'review':'Literal transcription from image by one development assistant, before predictions; not independently double annotated; evaluation-only'}
        rows.append(row)
        preview=crop.resize((min(970,crop.width),round(crop.height*min(970,crop.width)/crop.width)))
        sheet.paste(preview,(15,index*130+25))
        draw.text((15,index*130+3),f'{index}: writer {writer}',fill='black')
    (args.target/'reviewed_manifest.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
    sheet.save(args.target/'reviewed_contact.png')


if __name__=='__main__':
    main()
