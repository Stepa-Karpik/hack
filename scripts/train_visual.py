import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from torch.utils.data import Dataset,DataLoader
from PIL import Image
from dekanat.visual import build_model,TRANSFORM
from dekanat.schema import ROOT

class Zones(Dataset):
    def __init__(self,path,split):
        self.root=path
        self.records=[json.loads(line) for line in (path/split/"annotations.jsonl").read_text(encoding="utf-8").splitlines()]
    def __len__(self):return len(self.records)
    def __getitem__(self,index):
        row=self.records[index]
        with Image.open(self.root/row["visual_image"]) as image: tensor=TRANSFORM(image.convert("RGB"))
        return tensor,torch.tensor(row["visual_labels"],dtype=torch.float32)

def evaluate(model,loader,device):
    model.eval()
    probs,labels=[],[]
    with torch.inference_mode():
        for x,y in loader:
            probs.append(model(x.to(device)).sigmoid().cpu())
            labels.append(y)
    p=torch.cat(probs).numpy(); y=torch.cat(labels).numpy()
    return p,y

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,default=ROOT/"data")
    parser.add_argument("--epochs",type=int,default=8)
    parser.add_argument("--batch",type=int,default=32)
    parser.add_argument("--resume",type=Path)
    parser.add_argument("--output",type=Path,default=ROOT/"models"/"visual.pt")
    args=parser.parse_args()
    torch.manual_seed(42);random.seed(42);np.random.seed(42)
    torch.set_num_threads(4)
    device="cuda" if torch.cuda.is_available() else "cpu"
    model=build_model(pretrained=not bool(args.resume)).to(device)
    # Fine-tune final backbone blocks and classifier, preserving earlier ImageNet features.
    for parameter in model.features[:9].parameters():parameter.requires_grad=False
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.0005)
    start_epoch=0
    if args.resume:
        checkpoint=torch.load(args.resume,map_location="cpu",weights_only=True)
        model.load_state_dict(checkpoint["state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        start_epoch=checkpoint["epoch"]
    train=DataLoader(Zones(args.data,"train"),batch_size=args.batch,shuffle=True,num_workers=0)
    val=DataLoader(Zones(args.data,"val"),batch_size=args.batch,num_workers=0)
    test=DataLoader(Zones(args.data,"test"),batch_size=args.batch,num_workers=0)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    best=-1
    history=[]
    began=time.perf_counter()
    for epoch in range(start_epoch,args.epochs):
        model.train()
        model.features[:9].eval()
        total=0
        for x,y in train:
            optimizer.zero_grad(set_to_none=True)
            logits=model(x.to(device))
            loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,y.to(device))
            loss.backward();optimizer.step();total+=float(loss.detach())
        p,y=evaluate(model,val,device)
        accuracy=float(((p>.5)==y).mean())
        history.append({"epoch":epoch+1,"loss":total/len(train),"val_label_accuracy":accuracy})
        print(json.dumps(history[-1]),flush=True)
        checkpoint={"state_dict":model.state_dict(),"optimizer":optimizer.state_dict(),"epoch":epoch+1,
                    "thresholds":[.9,.9],"base":"torchvision MobileNet_V3_Small_Weights.DEFAULT", "seed":42}
        torch.save(checkpoint,args.output.with_name("visual.last.pt"))
        if accuracy>best:
            best=accuracy;torch.save(checkpoint,args.output)
    model.load_state_dict(torch.load(args.output,map_location="cpu",weights_only=True)["state_dict"])
    report={"scope":"Synthetic footer-zone classification only. Not validated on real signatures/stamps or arbitrary page layouts.",
            "base_weights":"torchvision MobileNet_V3_Small_Weights.DEFAULT (ImageNet)","device":device,
            "seconds":time.perf_counter()-began,"history":history,"positive_threshold":.9}
    for split,loader in [("val",val),("test",test)]:
        p,y=evaluate(model,loader,device)
        report[split]={"examples":len(y),"label_accuracy_at_0_5":float(((p>.5)==y).mean()),"classes":{}}
        for i,name in enumerate(["signature","stamp"]):
            pred=p[:,i]>=.9;truth=y[:,i]>0
            tp=int((pred&truth).sum());fp=int((pred&~truth).sum());fn=int((~pred&truth).sum())
            report[split]["classes"][name]={"precision":tp/max(1,tp+fp),"recall":tp/max(1,tp+fn),"tp":tp,"fp":fp,"fn":fn}
    (ROOT/"artifacts"/"visual_metrics.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="history"},indent=2),flush=True)

if __name__=="__main__":main()

