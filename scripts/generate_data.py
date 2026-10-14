import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import SCHEMAS,ROOT
from dekanat.synthetic import document,visual_zone

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"data")
    parser.add_argument("--count",type=int,default=1200)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={"source":"Team-generated synthetic documents; all personal data fictitious",
              "seed":20261010,"splits":{},"note":"Template families separated; synthetic visual strokes are not real handwriting."}
    for split,templates,amount in [("train",range(0,12),args.count),("val",range(12,16),max(100,args.count//5)),("test",range(16,20),max(100,args.count//5))]:
        target=args.output/split
        (target/"visual").mkdir(parents=True,exist_ok=True)
        records=[]
        for i in range(amount):
            seed=20261010+{"train":0,"val":100000,"test":200000}[split]+i
            image,record=document(seed,template=list(templates)[i%len(templates)])
            # Full pages only for the e2e sample, not every training row.
            if i<12:
                (target/"documents").mkdir(exist_ok=True)
                file=target/"documents"/f"{seed}.png"
                image.save(file)
                record["image"]=str(file.relative_to(args.output))
            visual,labels=visual_zone(seed,split)
            file=target/"visual"/f"{seed}.jpg"
            visual.save(file,quality=90 if split=="train" else 72)
            record["visual_image"]=str(file.relative_to(args.output))
            record["visual_labels"]=labels
            records.append(record)
        (target/"annotations.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in records),encoding="utf-8")
        manifest["splits"][split]={"count":amount,"templates":list(templates)}
        print(f"{split}: {amount} examples",flush=True)
    demos=args.output/"demo"
    demos.mkdir(exist_ok=True)
    for i,kind in enumerate(SCHEMAS):
        image,record=document(8100+i,template=1,document_type=kind)
        image.save(demos/f"{kind}.png")
        (demos/f"{kind}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    (args.output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__": main()

