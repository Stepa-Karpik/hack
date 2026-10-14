import argparse
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ultralytics import YOLO
from dekanat.schema import ROOT

def main():
    p=argparse.ArgumentParser();p.add_argument("--epochs",type=int,default=20);p.add_argument("--batch",type=int,default=8);p.add_argument("--data",type=Path,default=ROOT/"data"/"detection"/"dataset.yaml");p.add_argument("--device",default="0");args=p.parse_args()
    model=YOLO("yolov8n.pt")
    model.train(data=str(args.data),epochs=args.epochs,batch=args.batch,imgsz=640,device=args.device,
                workers=0,project=str(ROOT/"data"/"runs"),name="marks",exist_ok=True,
                seed=42,deterministic=True,patience=8,plots=False,save=True,
                fliplr=0.,flipud=0.,mosaic=.25,close_mosaic=5,verbose=False)
    weights=Path(model.trainer.best)
    shutil.copy2(weights,ROOT/"models"/"marks.pt")
    metrics=YOLO(str(weights)).val(data=str(args.data),device=args.device,plots=False,verbose=False)
    report={"base_weights":"yolov8n.pt; COCO pretrained; Ultralytics AGPL-3.0",
            "scope":"Mixed real-signature/synthetic-mark validation. Not a real-stamp benchmark.",
            "metrics":{k:float(v) for k,v in metrics.results_dict.items()}}
    (ROOT/"artifacts"/"detection_metrics.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2),flush=True)

if __name__=="__main__":main()

