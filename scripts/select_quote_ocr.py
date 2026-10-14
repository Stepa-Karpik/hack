"""Deploy only the narrow quote fallback after recorded regression checks."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--training-report", type=Path, default=ROOT/"artifacts/ocr_quotes_training_v2.json")
    args = parser.parse_args()
    def read(name):
        return json.loads((ROOT/"artifacts"/name).read_text(encoding="utf-8"))
    regression = read("narrative_regression.json")
    before = read("narrative_without_quote_metrics.json")
    after = read("narrative_candidate_metrics.json")
    fresh = read("narrative_candidate_fresh_metrics.json")
    training = json.loads(args.training_report.read_text(encoding="utf-8"))
    candidate_hash = hashlib.sha256(args.candidate.read_bytes()).hexdigest()
    parent_hash = hashlib.sha256((ROOT/"models/ocr_cyrillic.pt").read_bytes()).hexdigest()
    if training["candidate_sha256"] != candidate_hash or training["base_sha256"] != parent_hash:
        raise ValueError("Reports do not match candidate/parent weights")
    if regression.get("quote_candidate_sha256") != candidate_hash or regression.get("parent_sha256") != parent_hash:
        raise ValueError("Regression evidence belongs to different or unidentified weights")
    if regression.get("runtime_sha256") != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"dekanat").glob("*.py")}:
        raise ValueError("Runtime changed after regression evaluation")
    if regression.get("passed") is not True or len(regression.get("checks", [])) < 41 or not all(c.get("passed") is True for c in regression["checks"]):
        raise ValueError("Full recorded regression gate required")
    if before["documents"] != after["documents"] or before["total"] != after["total"]:
        raise ValueError("Different comparison cohorts")
    if [(r["type"], r["style"]) for r in before["rows"]] != [(r["type"], r["style"]) for r in after["rows"]]:
        raise ValueError("Different comparison layouts")
    if after["correct"] <= before["correct"]:
        raise ValueError("Quote fallback has no measured benefit")
    for report in [after, fresh]:
        if report["documents"] != 9 or report["total"] != 63 or report["confident_wrong"] != 0 or report["type_correct"] != 9:
            raise ValueError("Prose diagnostic checks failed")
        observed = [r["quote_recovery"]["weights_sha256"] for r in report["rows"] if (r.get("quote_recovery") or {}).get("attempts")]
        if not observed or any(value != candidate_hash for value in observed):
            raise ValueError("Prose suite did not run the candidate")
    target = ROOT/"models/ocr_quotes.pt"
    if target.resolve() != args.candidate.resolve():
        shutil.copy2(args.candidate, target)
    decision = {"enabled": True, "mode": "missing_quoted_study_fields", "sha256": candidate_hash, "base_sha256": parent_hash,
                "scope": "Only missing university/program fields in recognized study prose or bounded education headers; no global OCR replacement. These diagnostics do not prove real-world accuracy.",
                "before_correct": before["correct"], "after_correct": after["correct"], "fresh_correct": fresh["correct"], "total_per_suite": after["total"],
                "training_report": str(args.training_report),
                "evidence": ["narrative_regression.json", "narrative_without_quote_metrics.json", "narrative_candidate_metrics.json", "narrative_candidate_fresh_metrics.json", args.training_report.name]}
    (ROOT/"models/quote_selection.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT/"artifacts/quote_selection_metrics.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
