"""Fresh evaluation-only documents, separate from the examples used to debug."""
import json
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT,SCHEMAS
from dekanat.synthetic import document

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--split",choices=["audit","audit_final"],default="audit");args=parser.parse_args()
    target=ROOT/"data"/args.split;target.mkdir(parents=True,exist_ok=True)
    records=[]
    for i in range(36):
        kind=list(SCHEMAS)[i%3]
        seed=(9000000 if args.split=="audit" else 9500000)+i
        image,record=document(seed,template=(20 if args.split=="audit" else 40)+i%12,document_type=kind)
        file=target/f"{record['id']}.jpg"
        image.save(file,quality=80)
        record["image"]=str(file.relative_to(ROOT/"data"))
        records.append(record)
    (target/"annotations.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in records),encoding="utf-8")
    print("36 fresh audit documents. Same generator distribution; no claim of real-world generalization.")

if __name__=="__main__":main()

