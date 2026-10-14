import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from dekanat.pipeline import analyze
from dekanat.extraction import normalize

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,default=ROOT/"data")
    parser.add_argument("--limit",type=int,default=6)
    parser.add_argument("--split",default="test")
    parser.add_argument("--ocr",choices=["selected","baseline","candidate","cascade"],default="selected")
    parser.add_argument("--cpu",action="store_true")
    parser.add_argument("--retry",action="store_true")
    args=parser.parse_args()
    records=[json.loads(x) for x in (args.data/args.split/"annotations.jsonl").read_text(encoding="utf-8").splitlines()]
    rows=[];correct=0;total=0
    # Model initialization belongs to startup cost, not steady-state latency.
    from dekanat.ocr import get_reader
    variant={"selected":True,"baseline":False,"candidate":"candidate","cascade":"cascade"}[args.ocr]
    began=time.perf_counter();get_reader(not args.cpu,variant)
    warmup=args.data/"demo"/"study.png"
    if warmup.exists():analyze(warmup.read_bytes(),warmup.name,"study",not args.cpu,False,variant)
    startup=time.perf_counter()-began
    for record in [r for r in records if "image" in r][:args.limit]:
        file=args.data/record["image"]
        pages,result=analyze(file.read_bytes(),file.name,record["type"],not args.cpu,args.retry,variant)
        errors=[];whole=True
        for key,truth in record["fields"].items():
            if isinstance(truth,bool):continue
            value=result["fields"][key]["value"]
            is_correct=(truth is None and value is None) or (truth is not None and value is not None and normalize(str(truth))==normalize(str(value)))
            correct+=int(is_correct);total+=1;whole=whole and is_correct
            if not is_correct:errors.append({"field":key,"expected":truth,"actual":value})
        row={"id":record["id"],"type":record["type"],"seconds":result["seconds"],"whole_text_card_correct":whole,"errors":errors}
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    import numpy as np
    durations=[r["seconds"] for r in rows]
    report={"scope":"End-to-end EasyOCR + extraction on synthetic documents. No real-document quality claim. Visual fields excluded. Development test/audit examples were used for debugging and model selection; audit_final is a fresh run from the same generator.","split":args.split,"ocr":args.ocr,
            "documents":len(rows),"model_startup_seconds":startup,"field_exact_match":correct/max(1,total),"text_card_exact_match":sum(r["whole_text_card_correct"] for r in rows)/max(1,len(rows)),
            "median_seconds":float(np.median(durations)) if durations else None,"p95_seconds":float(np.percentile(durations,95)) if durations else None,"rows":rows}
    name=f"{Path(args.split).name}_{args.ocr}_metrics.json"
    (ROOT/"artifacts"/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()

