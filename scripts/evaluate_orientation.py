"""Diagnostic quarter-turn suite using known synthetic demo documents."""
import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT, SCHEMAS
from dekanat.extraction import normalize
from dekanat.pipeline import analyze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    rows = []
    for index, kind in enumerate(SCHEMAS):
        if args.fresh:
            from dekanat.synthetic import document
            source, record = document(2026101700+index, template=70+index, document_type=kind, missing_rate=0, force_marks=(True,True))
            truth = record["fields"]
        else:
            source = Image.open(ROOT/f"data/demo/{kind}.png").convert("RGB")
            truth = json.loads((ROOT/f"data/demo/{kind}.json").read_text(encoding="utf-8"))["fields"]
        for degrees in [0, 90, 180, 270]:
            image = source.rotate(degrees, expand=True)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            _, result = analyze(buffer.getvalue(), "quarter.png", "auto", retry=False, orientation=not args.baseline)
            correct, total, confident_wrong, errors = 0, 0, 0, []
            for key, expected in truth.items():
                if isinstance(expected, bool):
                    continue
                field = result["fields"].get(key, {"value": None, "status": "not_found"})
                equal = field["value"] is not None and normalize(str(field["value"])) == normalize(str(expected))
                correct += int(equal)
                total += 1
                confident_wrong += int(not equal and field["status"] == "found")
                if not equal:
                    errors.append({"field": key, "expected": expected, "actual": field["value"], "status": field["status"]})
            row = {"type": kind, "degrees": degrees, "detected_type": result["type"], "correct": correct, "total": total,
                   "confident_wrong": confident_wrong, "errors": errors, "seconds": result["seconds"], "orientation": result.get("orientation")}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {"scope": "12 deterministic cases from three synthetic documents x 0/90/180/270 degrees; automatic type, real OCR, visual fields excluded. Development diagnostic, not real camera/student-document accuracy. Fresh variant uses new seeds 2026101700-2026101702 and templates70-72 from the same generator after orientation selection.", "fresh": args.fresh,
              "documents": len(rows), "type_correct": sum(r["detected_type"] == r["type"] for r in rows),
              "correct": sum(r["correct"] for r in rows), "total": sum(r["total"] for r in rows), "confident_wrong": sum(r["confident_wrong"] for r in rows), "rows": rows}
    name = "baseline" if args.baseline else "candidate"
    suffix = "_fresh" if args.fresh else ""
    (ROOT/f"artifacts/orientation_{name}{suffix}_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
