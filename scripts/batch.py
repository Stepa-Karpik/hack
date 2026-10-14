"""Internal batch contract; organizer results.json format has not been provided."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import load_policy
from dekanat.pipeline import analyze,respond

def main():
    p=argparse.ArgumentParser();p.add_argument("input",type=Path);p.add_argument("--output",type=Path,default=Path("results.json"));p.add_argument("--policy",type=Path)
    args=p.parse_args();policy=load_policy(args.policy);results=[]
    cache={}
    for line in args.input.read_text(encoding="utf-8").splitlines():
        item=json.loads(line);file=args.input.parent/item["file"]
        key=(str(file.resolve()),item.get("type","auto"))
        try:
            if key not in cache:cache[key]=analyze(file.read_bytes(),file.name,key[1])[1]
            analysis=cache[key]
            results.append({"id":item["id"],"fields":analysis["fields"],"response":respond(analysis,item["question"],policy),"demo_policy":policy.get("demo",False)})
        except Exception as error:results.append({"id":item["id"],"error":str(error)})
    args.output.write_text(json.dumps({"format":"team-internal-v1","results":results},ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":main()

