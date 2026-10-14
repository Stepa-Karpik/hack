"""Deploy a fine-tuned OCR only after comparing the complete field pipeline."""
import json
import hashlib
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT

def main():
    target=ROOT/"models"/"ocr_selection.json"
    target.write_text(json.dumps({"enabled":False,"reason":"Comparison pending"}),encoding="utf-8")
    for variant in ["baseline","candidate","cascade"]:
        subprocess.run([sys.executable,"-X","utf8",str(ROOT/"scripts"/"evaluate.py"),"--split","audit","--limit","36","--ocr",variant],cwd=ROOT,check=True)
    baseline=json.loads((ROOT/"artifacts"/"audit_baseline_metrics.json").read_text(encoding="utf-8"))
    global_candidate=json.loads((ROOT/"artifacts"/"audit_candidate_metrics.json").read_text(encoding="utf-8"))
    cascade_candidate=json.loads((ROOT/"artifacts"/"audit_cascade_metrics.json").read_text(encoding="utf-8"))
    acceptable=[("global",global_candidate),("numeric_cascade",cascade_candidate)]
    acceptable=[(mode,data) for mode,data in acceptable if data["text_card_exact_match"]>=baseline["text_card_exact_match"]]
    mode,candidate=max(acceptable,key=lambda x:x[1]["field_exact_match"]) if acceptable else ("global",global_candidate)
    enabled=candidate["field_exact_match"]>baseline["field_exact_match"] and candidate["text_card_exact_match"]>=baseline["text_card_exact_match"]
    report={"enabled":enabled,"mode":mode if enabled else "baseline","scope":"Selection on development audit, not independent final evaluation",
            "baseline_fields":baseline["field_exact_match"],"candidate_fields":candidate["field_exact_match"],
            "baseline_cards":baseline["text_card_exact_match"],"candidate_cards":candidate["text_card_exact_match"],
            "reason":"Candidate improves fields without degrading card exact match" if enabled else "Keep baseline: candidate did not improve the full field pipeline",
            "sha256":hashlib.sha256((ROOT/"models"/"ocr_cyrillic.pt").read_bytes()).hexdigest()}
    target.write_text(json.dumps(report,indent=2),encoding="utf-8")
    (ROOT/"artifacts"/"ocr_selection.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2),flush=True)

if __name__=="__main__":main()

