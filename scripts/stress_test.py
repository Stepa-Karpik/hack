"""Diagnostic distortions of known demo images, not an independent quality test."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageFilter
from dekanat.schema import ROOT, SCHEMAS
from dekanat.pipeline import analyze
from dekanat.extraction import normalize


def shadow(image):
    array = np.asarray(image).astype(float)
    factor = np.linspace(.45, 1., image.width)[None, :, None]
    return Image.fromarray(np.clip(array * factor, 0, 255).astype("uint8"))


def main():
    transforms = {
        "original": lambda x: x,
        "rotate_10": lambda x: x.rotate(10, Image.Resampling.BICUBIC, expand=True, fillcolor="white"),
        "rotate_30": lambda x: x.rotate(30, Image.Resampling.BICUBIC, expand=True, fillcolor="white"),
        "blur_1_2": lambda x: x.filter(ImageFilter.GaussianBlur(1.2)),
        "shadow_45_percent": shadow,
        "half_resolution": lambda x: x.resize((x.width//2, x.height//2), Image.Resampling.LANCZOS),
    }
    demo = ROOT / "data" / "demo"
    analyze((demo / "study.png").read_bytes(), "study.png", "study", retry=False)
    rows = []
    for kind in SCHEMAS:
        truth = json.loads((demo / f"{kind}.json").read_text(encoding="utf-8"))["fields"]
        with Image.open(demo / f"{kind}.png") as source:
            source = source.convert("RGB")
        for name, transform in transforms.items():
            buffer = io.BytesIO()
            transform(source).save(buffer, format="PNG")
            _, result = analyze(buffer.getvalue(), "stress.png", kind, retry=False)
            errors, correct, total = [], 0, 0
            for key, expected in truth.items():
                if isinstance(expected, bool):
                    continue
                actual = result["fields"][key]["value"]
                equal = expected is None and actual is None or expected is not None and actual is not None and normalize(str(expected)) == normalize(str(actual))
                total += 1
                correct += int(equal)
                if not equal:
                    errors.append({"field": key, "expected": expected, "actual": actual})
            row = {"type": kind, "distortion": name, "correct": correct, "total": total,
                   "seconds": result["seconds"], "errors": errors}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {}
    for name in transforms:
        group = [r for r in rows if r["distortion"] == name]
        summary[name] = {"correct": sum(r["correct"] for r in group), "total": sum(r["total"] for r in group),
                         "median_seconds": float(np.median([r["seconds"] for r in group]))}
    report = {"scope": "Diagnostic only: three known synthetic demos, six deterministic distortions each. Manual document type, selected OCR, GPU, retry disabled. Visual fields excluded. Not independent evaluation or real camera captures.",
              "summary": summary, "rows": rows}
    (ROOT / "artifacts" / "stress_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
