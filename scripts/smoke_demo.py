import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT,load_policy
from dekanat.pipeline import analyze,respond

def main():
    reports=[];policy=load_policy()
    for name in ["study","leave","practice","study_missing"]:
        file=ROOT/"data"/"demo"/(name+".png")
        _,analysis=analyze(file.read_bytes(),file.name,retry=True)
        reply=respond(analysis,"Все ли обязательные сведения есть в документе?",policy)
        unknown=respond(analysis,"Какая стоимость обучения?",policy)
        assert analysis["type"] is not None
        assert unknown["status"]=="no_answer"
        if name=="study_missing":assert analysis["fields"]["issue_date"]["value"] is None and reply["status"]=="insufficient"
        row={"document":name,"seconds":analysis["seconds"],"response":reply,
             "fields":{key:{k:v for k,v in value.items() if k!="evidence"} for key,value in analysis["fields"].items()}}
        reports.append(row);print(json.dumps({"document":name,"status":reply["status"],"answer":reply["answer"]},ensure_ascii=False),flush=True)
    (ROOT/"artifacts"/"demo_smoke.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":main()

