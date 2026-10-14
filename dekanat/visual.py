from functools import lru_cache
from pathlib import Path
import torch
from torchvision import models, transforms

def build_model(pretrained=False):
    weights=models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model=models.mobilenet_v3_small(weights=weights)
    model.classifier[-1]=torch.nn.Linear(model.classifier[-1].in_features,2)
    return model

TRANSFORM=transforms.Compose([transforms.Resize((160,400)),transforms.ToTensor(),
    transforms.Normalize([.485,.456,.406],[.229,.224,.225])])

@lru_cache(maxsize=2)
def load_model(path,mtime,device):
    model=build_model()
    checkpoint=torch.load(path,map_location="cpu",weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    return model.to(device).eval(),checkpoint.get("thresholds",[.8,.8])

@lru_cache(maxsize=2)
def load_detector(path,mtime):
    from ultralytics import YOLO
    return YOLO(path)

def detect_marks(pages,required,path,gpu=True):
    import numpy as np
    detector=load_detector(str(path),Path(path).stat().st_mtime)
    device=0 if gpu and torch.cuda.is_available() else "cpu"
    fields={k:{"value":False,"status":"uncertain","confidence":0.,"evidence":None} for k in required}
    for page_id,page in enumerate(pages):
        results=detector.predict(np.asarray(page)[:,:,::-1].copy(),imgsz=640,conf=.25,device=device,verbose=False)
        for x1,y1,x2,y2,confidence,cls in results[0].boxes.data.cpu().tolist():
            key={0:"signature",1:"stamp"}.get(int(cls))
            if key not in required or confidence<=fields[key]["confidence"]:continue
            fields[key]={"value":True,"status":"found" if confidence>=.8 else "uncertain","confidence":confidence,
                         "evidence":{"page":page_id,"bbox":[x1,y1,x2,y2],"method":"finetuned_yolov8n",
                                     "note":"Реальные подписи + синтетика; печати проверены только на синтетике. Наличие не доказывает подлинность."}}
    return fields

def classify(pages,required,model_path,gpu=True):
    detection=Path(model_path).with_name("marks.pt")
    if detection.exists():return detect_marks(pages,required,detection,gpu)
    result={k:{"value":None,"status":"uncertain","confidence":0.,"evidence":None} for k in required}
    if not Path(model_path).exists(): return result
    device="cuda" if gpu and torch.cuda.is_available() else "cpu"
    model,thresholds=load_model(str(model_path),Path(model_path).stat().st_mtime,device)
    # Trained on synthetic footer zones only: do not present an absence as conclusive.
    for page_id,page in enumerate(pages):
        w,h=page.size
        box=[0,int(h*.72),w,h]
        crop=page.crop(box)
        with torch.inference_mode(): probabilities=model(TRANSFORM(crop).unsqueeze(0).to(device)).sigmoid()[0].cpu().tolist()
        for index,key in enumerate(["signature","stamp"]):
            if key not in required: continue
            confidence=probabilities[index]
            if confidence>result[key]["confidence"]:
                result[key]={"value":bool(confidence>=thresholds[index]),
                             "status":"uncertain", "confidence":float(confidence),
                             "evidence":{"page":page_id,"bbox":box,"method":"synthetic_footer_classifier",
                                         "note":"Экспериментальная модель: предсказание требует проверки; отсутствие вне нижней зоны не проверено."}}
    return result

