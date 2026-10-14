"""Fine-tune the actual EasyOCR Cyrillic recognizer on synthetic field crops."""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from torch.utils.data import DataLoader,Dataset
from easyocr.recognition import NormalizePAD
from easyocr.easyocr import imgH
from dekanat.ocr import get_reader
from dekanat.schema import ROOT,SCHEMAS
from dekanat.synthetic import values,font_path

def distance(a,b):
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        row=[i]
        for j,cb in enumerate(b,1):row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(ca!=cb)))
        prev=row
    return prev[-1]

class Crops(Dataset):
    def __init__(self,count,seed,character,validation=False):
        self.rows=[];self.pad=NormalizePAD((1,imgH,512))
        rng=random.Random(seed)
        fonts=[p for p in ["C:/Windows/Fonts/arial.ttf","C:/Windows/Fonts/times.ttf","C:/Windows/Fonts/georgia.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if Path(p).exists()]
        if validation and Path("C:/Windows/Fonts/calibri.ttf").exists():fonts=["C:/Windows/Fonts/calibri.ttf"]
        if not fonts:fonts=[font_path()]
        aliases=[a for schema in SCHEMAS.values() for aa in schema["fields"].values() for a in aa]
        for i in range(count):
            data=values(rng);mode=rng.random()
            if mode<.35:text=rng.choice([f"УЧ-{rng.randint(1,9999):04d}",f"ИТ-{rng.randint(10,99)}",str(rng.randint(1,9))])
            elif mode<.55:text=rng.choice([data["issue_date"],data["study_period"],data["start_date"],data["end_date"]])
            elif mode<.75:text=rng.choice(aliases)
            else:text=rng.choice(list(data.values()))
            text="".join(c for c in text if c in character)
            font=ImageFont.truetype(rng.choice(fonts),rng.randint(18,38))
            box=font.getbbox(text);margin=rng.randint(3,8)
            image=Image.new("L",(box[2]-box[0]+2*margin,box[3]-box[1]+2*margin),rng.randint(235,255))
            draw=ImageDraw.Draw(image);draw.text((margin-box[0],margin-box[1]),text,font=font,fill=rng.randint(0,60))
            if rng.random()<.3:image=image.filter(ImageFilter.GaussianBlur(rng.uniform(.15,.65)))
            width=min(512,math.ceil(imgH*image.width/image.height))
            image=image.resize((width,imgH),Image.Resampling.BICUBIC)
            self.rows.append((self.pad(image),text))
    def __len__(self):return len(self.rows)
    def __getitem__(self,index):return self.rows[index]

def evaluate(model,loader,converter,device):
    model.eval();correct=0;chars=0;errors=0;total=0
    with torch.inference_mode():
        for x,texts in loader:
            logits=model(x.to(device),None)
            best=logits.argmax(2).cpu()
            length=torch.IntTensor([best.shape[1]]*len(texts))
            predictions=converter.decode_greedy(best.reshape(-1).numpy(),length.numpy())
            for truth,pred in zip(texts,predictions):
                correct+=int(truth==pred);errors+=distance(truth,pred);chars+=len(truth);total+=1
    return {"exact_match":correct/total,"cer":errors/chars,"examples":total}

def main():
    p=argparse.ArgumentParser();p.add_argument("--epochs",type=int,default=6);p.add_argument("--count",type=int,default=2400);p.add_argument("--batch",type=int,default=32);p.add_argument("--lr",type=float,default=.00003)
    p.add_argument("--output",type=Path,default=ROOT/"models"/"ocr_cyrillic.pt")
    p.add_argument("--report",type=Path,default=ROOT/"artifacts"/"ocr_training_metrics.json")
    args=p.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.report.parent.mkdir(parents=True,exist_ok=True)
    torch.manual_seed(42);torch.set_num_threads(4)
    reader=get_reader(True,finetuned=False);device=reader.device
    model=getattr(reader.recognizer,"module",reader.recognizer)
    train=DataLoader(Crops(args.count,42001,reader.character),batch_size=args.batch,shuffle=True,num_workers=0)
    val=DataLoader(Crops(480,73001,reader.character,True),batch_size=args.batch,num_workers=0)
    baseline=evaluate(model,val,reader.converter,device)
    print("BASELINE "+json.dumps(baseline),flush=True)
    for parameter in model.FeatureExtraction.parameters():parameter.requires_grad=False
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=args.lr,weight_decay=.00001)
    loss_function=torch.nn.CTCLoss(blank=0,zero_infinity=True)
    history=[];best=baseline["exact_match"];best_cer=baseline["cer"];saved=False;began=time.perf_counter()
    for epoch in range(args.epochs):
        model.train();model.FeatureExtraction.eval();loss_sum=0
        for x,texts in train:
            optimizer.zero_grad(set_to_none=True)
            targets,lengths=reader.converter.encode(texts)
            logits=model(x.to(device),None).log_softmax(2)
            input_lengths=torch.IntTensor([logits.shape[1]]*len(texts))
            loss=loss_function(logits.permute(1,0,2),targets.to(device),input_lengths.to(device),lengths.to(device))
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();loss_sum+=float(loss.detach())
        result=evaluate(model,val,reader.converter,device)
        row={"epoch":epoch+1,"loss":loss_sum/len(train),**result};history.append(row);print(json.dumps(row),flush=True)
        if result["exact_match"]>best and result["cer"]<=best_cer:
            best=result["exact_match"];best_cer=result["cer"];saved=True
            checkpoint={"state_dict":{k:v.cpu() for k,v in model.state_dict().items()},"character":reader.character,
                        "base":"EasyOCR 1.7.2 cyrillic_g2 recognition weights","seed":42,"validation":result}
            torch.save(checkpoint,args.output)
    report={"scope":"Synthetic text crop validation, held-out font where available. Not handwriting or real student documents.",
            "base_weights":"EasyOCR 1.7.2 cyrillic_g2","train_examples":args.count,"baseline":baseline,"history":history,
            "exported":saved,"lr":args.lr,"best_exact_match":best,"best_cer":best_cer,"seconds":time.perf_counter()-began,"device":str(device)}
    report["output"]=str(args.output);args.report.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="history"},indent=2),flush=True)

if __name__=="__main__":main()

