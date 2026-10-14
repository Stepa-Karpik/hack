"""Fail closed on missing evidence or regression; never replace deployed weights."""
import argparse,json,math
from pathlib import Path


def check(plan,root):
    results=[]
    for item in plan["checks"]:
        before=json.loads((root/item["before"]).read_text(encoding="utf-8"))
        after=json.loads((root/item["after"]).read_text(encoding="utf-8"))
        metric=item["metric"]
        def metric_value(report):
            for part in metric.split("."):report=report[part]
            return report
        a=metric_value(before);b=metric_value(after)
        if isinstance(a,bool) or isinstance(b,bool) or not isinstance(a,(float,int)) or not isinstance(b,(float,int)) or not math.isfinite(a) or not math.isfinite(b):raise ValueError("Finite numeric metric required")
        for size in ("documents","total","cases","conditions"):
            if size in before or size in after:
                if before.get(size)!=after.get(size):raise ValueError("Evaluation sample sizes differ")
        if "rows" in before and "rows" in after:
            def identities(report):
                return [(r.get("id"),r.get("type"),r.get("style"),r.get("condition")) for r in report["rows"]]
            if identities(before)!=identities(after):raise ValueError("Evaluation cohorts differ")
        direction=item.get("direction","higher")
        if direction not in ["higher","lower"]:raise ValueError("Unknown metric direction")
        tolerance=item.get("tolerance",0)
        if tolerance<0:raise ValueError("Negative tolerance")
        passed=b>=a-tolerance if direction=="higher" else b<=a+tolerance
        results.append({"id":item["id"],"metric":metric,"before":a,"after":b,"passed":passed})
    if not results:raise ValueError("No checks: deployment is not approved")
    return {"passed":all(x["passed"] for x in results),"scope":"These recorded suites only; not a guarantee of real-world non-regression", "checks":results}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("plan",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    report=check(json.loads(args.plan.read_text(encoding="utf-8")),args.plan.parent)
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    if not report["passed"]:raise SystemExit(1)


if __name__=="__main__":main()
