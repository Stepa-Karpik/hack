"""Offline object-level threshold diagnosis; never changes deployed weights or thresholds."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ultralytics import YOLO
from PIL import Image
from dekanat.schema import ROOT


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0.


def score(rows, threshold):
    counts = {str(c): {"tp": 0, "fp": 0, "fn": 0} for c in (0, 1)}
    for row in rows:
        unmatched = list(row["targets"])
        for prediction in sorted(row["predictions"], key=lambda p: -p[4]):
            if prediction[4] < threshold:
                continue
            cls = str(int(prediction[5]))
            matches = [(iou(prediction[:4], target[1:]), i) for i, target in enumerate(unmatched) if str(target[0]) == cls]
            overlap, index = max(matches, default=(0., -1))
            if overlap >= .5:
                counts[cls]["tp"] += 1
                unmatched.pop(index)
            else:
                counts[cls]["fp"] += 1
        for target in unmatched:
            counts[str(target[0])]["fn"] += 1
    return counts


def main():
    model_path = ROOT/"models/marks.pt"
    model = YOLO(str(model_path))
    rows = []
    for path in sorted((ROOT/"data/detection/images/val").glob("*")):
        w, h = Image.open(path).size
        targets = []
        label = ROOT/"data/detection/labels/val"/(path.stem+".txt")
        for line in label.read_text(encoding="utf-8").splitlines():
            cls, x, y, bw, bh = map(float, line.split())
            targets.append([int(cls), (x-bw/2)*w, (y-bh/2)*h, (x+bw/2)*w, (y+bh/2)*h])
        predictions = model.predict(str(path), imgsz=640, conf=.25, device=0, verbose=False)[0].boxes.data.cpu().tolist()
        rows.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "cohort": "real" if path.name.startswith("real_") else "synthetic", "targets": targets, "predictions": predictions})
    manual = ROOT.parent/"Документы-для-проверки"
    observed = json.loads((manual/"РЕЗУЛЬТАТЫ_ТЕКУЩЕЙ_СБОРКИ.json").read_text(encoding="utf-8"))
    truth = {r["file"]: r for r in json.loads((manual/"ОЖИДАЕМЫЕ_ПОЛЯ.json").read_text(encoding="utf-8"))["records"]}
    manual_rows = []
    for row in observed["rows"]:
        for key in ("signature", "stamp"):
            if key not in row["fields"]:
                continue
            field = row["fields"][key]
            manual_rows.append({"file": row["file"], "field": key, "expected": truth[row["file"]]["expected_fields"][key],
                                "value": field["value"], "status": field["status"], "confidence": field["confidence"], "evidence": field["evidence"]})
    report = {"scope": "Development diagnosis: original checkpoint-selection validation, 35 real-signature/60 synthetic images. Object matching at IoU>=0.5, greedy by confidence; not Ultralytics AP or independent student-document accuracy. Manual results are frozen v9 full-pipeline observations, 18 related synthetic inputs including PDF duplicates; not fresh inference.",
              "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(), "prediction_settings": {"imgsz": 640, "conf": .25, "device": 0},
              "thresholds": {str(t): {cohort: score([r for r in rows if r["cohort"] == cohort], t) for cohort in ("real", "synthetic")} for t in (.25, .8, .85, .9, .95)},
              "validation_rows": rows, "manual_fields": manual_rows,
              "manual_confident_false_presence": [r for r in manual_rows if not r["expected"] and r["value"] is True and r["status"] == "found"],
              "manual_uncertain_false_candidates": [r for r in manual_rows if not r["expected"] and r["value"] is True and r["status"] == "uncertain"],
              "decision": "Keep deployed thresholds/weights unchanged. UI must say unconfirmed for uncertain candidates, regardless of bool value. No calibrated probability or authenticity claim."}
    destination = ROOT/"artifacts/mark_threshold_diagnostic.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("thresholds", "manual_confident_false_presence", "manual_uncertain_false_candidates", "decision")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
