"""Fictional literal-reading controls; no organizer reference or training import."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image,ImageFont,ImageDraw

LINES=['Вяземский Елисей Никитич','Жарков Савелий Матвеевич',
       'ООО «Квантовый берег»','07.11.2027 · 18.06.2029',
       'А0-О8-109 · КВ-48206','Юэлин Сэвиан Фёдорович']


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--font-dir',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise ValueError('Fresh control directory required')
    args.output.mkdir(parents=True);rows=[]
    for i,font_name in enumerate(['arial.ttf','times.ttf','calibri.ttf','verdana.ttf']):
        font_file=args.font_dir/font_name
        for size in [20,28]:
            image=Image.new('RGB',(1132,1600),'white');draw=ImageDraw.Draw(image)
            font=ImageFont.truetype(str(font_file),size)
            for j,line in enumerate(LINES):draw.text((120,240+j*65),line,font=font,fill='black')
            file=args.output/f'{i}-{size}.png';image.save(file)
            rows.append({'image':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                'expected_lines':LINES,'font':font_name,'size':size,
                'font_sha256':hashlib.sha256(font_file.read_bytes()).hexdigest()})
    (args.output/'manifest.json').write_text(json.dumps({'source':'original fictional literal controls',
        'license':'AGPL-3.0 project code; fonts not redistributed','trained':False,
        'scope':'8 viewed synthetic OCR controls with shared six strings across fonts; not independent field/app accuracy',
        'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Eight fictional OCR control pages prepared')


if __name__=='__main__':main()
