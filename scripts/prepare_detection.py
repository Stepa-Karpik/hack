"""Mix actual signature boxes with synthetic marks. Preserve source split groups."""
import argparse
import json
import random
import shutil
import sys
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from PIL import Image,ImageDraw,ImageFont
from dekanat.synthetic import signature,stamp,font_path
from dekanat.schema import ROOT

URL="https://github.com/ultralytics/assets/releases/download/v0.0.0/signature.zip"

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=ROOT/"data"/"detection");p.add_argument("--synthetic",type=int,default=240)
    args=p.parse_args();target=args.output.resolve();target.mkdir(parents=True,exist_ok=True)
    archive=target/"signature.zip"
    if not archive.exists():
        with requests.get(URL,stream=True,timeout=120) as response:
            response.raise_for_status()
            with archive.open("wb") as f:
                for chunk in response.iter_content(1024*1024):f.write(chunk)
    with zipfile.ZipFile(archive) as z:
        base=target/"source";base.mkdir(exist_ok=True)
        for member in z.infolist():
            if not (base/member.filename).resolve().is_relative_to(base.resolve()):raise ValueError("Unsafe archive path")
        z.extractall(base)
    source_images=list((target/"source").rglob("images"))
    if not source_images:raise ValueError("No image directory in signature dataset")
    source=source_images[0].parent
    counts={}
    for split in ["train","val"]:
        images=target/"images"/split;labels=target/"labels"/split
        images.mkdir(parents=True,exist_ok=True);labels.mkdir(parents=True,exist_ok=True)
        candidates=list((source/"images"/split).glob("*"))
        if not candidates:
            candidates=list((source/"images"/("valid" if split=="val" else split)).glob("*"))
        real=0
        for file in candidates:
            if file.suffix.lower() not in [".jpg",".jpeg",".png"]:continue
            label=source/"labels"/file.parent.name/(file.stem+".txt")
            if not label.exists():continue
            shutil.copy2(file,images/("real_"+file.name))
            (labels/("real_"+file.stem+".txt")).write_text(label.read_text(),encoding="utf-8")
            real+=1
        amount=args.synthetic if split=="train" else max(60,args.synthetic//4)
        for i in range(amount):
            rng=random.Random(300000+i+(0 if split=="train" else 100000))
            image=Image.new("RGB",(800,1100),rng.choice(["white","#faf8f2"]))
            draw=ImageDraw.Draw(image);font=ImageFont.truetype(font_path(),rng.randint(17,24))
            for y in range(40,1030,55):
                draw.text((30,y),rng.choice(["УЧЕБНЫЙ ОБРАЗЕЦ / Справка об обучении", "ФИО студента: Иванов Иван Иванович", "Дата выдачи: 05.10.2026", "Подпись: __________   М.П.", "Организация: Учебный центр", "Номер документа: УЧ-2026"]),font=font,fill="#252525")
            boxes=[]
            for cls in [0,1]:
                if rng.random()<.23:continue
                w,h=(rng.randint(110,200),rng.randint(35,75)) if cls==0 else (rng.randint(85,135),rng.randint(85,135))
                x,y=rng.randint(40,760-w),rng.randint(180,1050-h)
                (signature if cls==0 else stamp)(draw,rng,(x,y,w,h))
                boxes.append(f"{cls} {(x+w/2)/800:.6f} {(y+h/2)/1100:.6f} {w/800:.6f} {h/1100:.6f}")
            # Blue geometric logos: deliberate negatives.
            if rng.random()<.4:draw.rectangle((700,40,765,105),outline="#224499",width=4)
            image.save(images/f"synthetic_{i}.jpg",quality=rng.randint(65,95))
            (labels/f"synthetic_{i}.txt").write_text("\n".join(boxes),encoding="utf-8")
        counts[split]={"real":real,"synthetic":amount}
    import yaml
    config={"path":str(target),"train":"images/train","val":"images/val","names":{0:"signature",1:"stamp"}}
    (target/"dataset.yaml").write_text(yaml.safe_dump(config,allow_unicode=True),encoding="utf-8")
    report={"source_url":URL,"source_license":"AGPL-3.0 per Ultralytics dataset documentation","counts":counts,
            "scope":"Real signature boxes + synthetic signatures/stamps. No real stamp evaluation. Original real train/val split preserved."}
    (ROOT/"artifacts"/"detection_data.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2),flush=True)

if __name__=="__main__":main()

