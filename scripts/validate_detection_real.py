import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import yaml
from ultralytics import YOLO
from dekanat.schema import ROOT

def main():
    root=ROOT/"data"/"detection"
    images=list((root/"source").rglob("images"))[0]
    path=images.parent
    config={"path":str(path.resolve()),"train":"images/train","val":"images/val","names":{0:"signature",1:"stamp"}}
    file=root/"real_signature.yaml";file.write_text(yaml.safe_dump(config),encoding="utf-8")
    model=YOLO(str(ROOT/"models"/"marks.pt"))
    result=model.val(data=str(file),device=0,plots=False,verbose=False)
    report={"scope":"Original Ultralytics real-signature validation set only (35 images), used for checkpoint selection through mixed validation. Not independent real-student test; no real stamp targets.",
            "metrics":{k:float(v) for k,v in result.results_dict.items()}}
    (ROOT/"artifacts"/"real_signature_metrics.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()

