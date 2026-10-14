import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT,SCHEMAS
from dekanat.synthetic import document

def main():
    target=ROOT/"data"/"demo";target.mkdir(parents=True,exist_ok=True)
    for i,kind in enumerate(SCHEMAS):
        image,record=document(8200+i,template=0,document_type=kind,missing_rate=0,force_marks=(True,True))
        image.save(target/f"{kind}.png")
        (target/f"{kind}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    image,record=document(8300,template=2,document_type="study",missing_rate=0,force_marks=(True,False),omitted=["issue_date"])
    image.save(target/"study_missing.png")
    (target/"study_missing.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Four explicit demo scenarios created")

if __name__=="__main__":main()

