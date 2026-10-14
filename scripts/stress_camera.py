"""Compare preprocessing variants on controlled camera-like synthetic cases."""
import argparse
import io
import json
import sys
import hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from dekanat.schema import ROOT,SCHEMAS
from dekanat.photo_augment import conditions
from dekanat.pipeline import analyze
from dekanat.extraction import normalize


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["deskew","photo"],default="photo")
    parser.add_argument("--retry",action="store_true")
    parser.add_argument("--set",choices=["demo","fresh"],default="demo")
    args=parser.parse_args()
    transforms=conditions();demo=ROOT/"data/demo"
    analyze((demo/"study.png").read_bytes(),"warmup.png","study",retry=False)
    rows=[]
    for index,kind in enumerate(SCHEMAS):
        if args.set=="fresh":
            from dekanat.synthetic import document
            source,record=document(9800000+index,template=52+index,document_type=kind,missing_rate=0,force_marks=(True,True))
            truth=record["fields"]
        else:
            truth=json.loads((demo/f"{kind}.json").read_text(encoding="utf-8"))["fields"]
            with Image.open(demo/f"{kind}.png") as image: source=image.convert("RGB")
        for name,transform in transforms.items():
            image=transform(source);buffer=io.BytesIO();image.save(buffer,format="PNG")
            _,result=analyze(buffer.getvalue(),"camera.png",kind,retry=args.retry,photo=args.mode=="photo")
            errors=[];correct=0;total=0;confident_wrong=0
            for key,expected in truth.items():
                if isinstance(expected,bool):continue
                field=result["fields"][key];actual=field["value"]
                equal=expected is None and actual is None or expected is not None and actual is not None and normalize(str(expected))==normalize(str(actual))
                total+=1;correct+=int(equal)
                if not equal:
                    confident_wrong+=int(field["status"]=="found")
                    errors.append({"field":key,"expected":expected,"actual":actual,"status":field["status"]})
            row={"type":kind,"condition":name,"correct":correct,"total":total,"confident_wrong":confident_wrong,
                 "seconds":result["seconds"],"errors":errors,"preprocessing":result["preprocessing"]}
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k not in ["errors","preprocessing"]}),flush=True)
    summary={}
    for name in transforms:
        group=[r for r in rows if r["condition"]==name]
        summary[name]={"correct":sum(r["correct"] for r in group),"total":sum(r["total"] for r in group),
                       "confident_wrong":sum(r["confident_wrong"] for r in group),"median_seconds":float(np.median([r["seconds"] for r in group]))}
    scope="Three new synthetic documents, seeds 9800000–9800002, templates 52–54, same generator as training. First evaluation after preprocessing selection; not real photos." if args.set=="fresh" else "Diagnostic: three known synthetic demos; used to choose preprocessing. Not independent test."
    report={"scope":scope+" Deterministic camera-like transformations; manual type; visual fields excluded.","set":args.set,
            "mode":args.mode,"retry":args.retry,"cases":len(rows),"conditions":len(transforms),"summary":summary,"rows":rows,
            "augmentation_sha256":hashlib.sha256((ROOT/"dekanat/photo_augment.py").read_bytes()).hexdigest()}
    suffix="_fresh" if args.set=="fresh" else ""
    (ROOT/f"artifacts/camera_{args.mode}{suffix}_metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()
