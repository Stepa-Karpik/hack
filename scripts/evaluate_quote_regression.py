"""Isolated full candidate evaluation; does not alter deployed weights/selection."""
import argparse
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from scripts.check_regression import check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    import dekanat.pipeline as pipeline
    original_state, original_argv, original_cwd = pipeline.quote_state, sys.argv, Path.cwd()
    try:
        os.chdir(ROOT)
        pipeline.quote_state = lambda: candidate
        def run(script, *arguments):
            sys.argv = [script, *arguments]
            runpy.run_path(str(ROOT/"scripts"/script), run_name="__main__")
        if not (ROOT/"data/audit/annotations.jsonl").exists():
            run("make_audit.py", "--split", "audit")
        run("evaluate_narrative.py", "--previous")
        run("evaluate_narrative.py", "--without-quote")
        run("evaluate_narrative.py", "--quote-model", str(candidate))
        run("evaluate_narrative.py", "--quote-model", str(candidate), "--fresh")
        run("evaluate.py", "--split", "audit", "--limit", "36", "--ocr", "selected")
        run("evaluate_layouts.py")
        run("stress_camera.py", "--mode", "photo")
        plan = ROOT/"configs/narrative_regression.json"
        report = check(json.loads(plan.read_text(encoding="utf-8")), plan.parent)
        report.update(quote_candidate_sha256=candidate_hash,
                      parent_sha256=hashlib.sha256((ROOT/"models/ocr_cyrillic.pt").read_bytes()).hexdigest(),
                      evaluation_method="Full isolated candidate run: source suite scripts with explicit pipeline.quote_state override; deployed selection files unchanged.",
                      runtime_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"dekanat").glob("*.py")})
        assert candidate_hash == hashlib.sha256(candidate.read_bytes()).hexdigest(), "Candidate changed during evaluation"
        (ROOT/"artifacts/narrative_regression.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "candidate_sha256": candidate_hash}), flush=True)
        if not report["passed"]:
            raise SystemExit(1)
    finally:
        pipeline.quote_state, sys.argv = original_state, original_argv
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()
