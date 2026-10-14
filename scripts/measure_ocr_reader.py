"""Isolated reader startup/tensor-memory measurement; not whole-app latency."""
import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT


def one(detector):
    import torch
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from dekanat.ocr import get_reader
    from dekanat.synthetic import font_path
    torch.cuda.init()
    torch.cuda.synchronize()
    before = torch.cuda.memory_allocated()
    began = time.perf_counter()
    reader = get_reader(True, "candidate", detector=detector)
    torch.cuda.synchronize()
    startup = time.perf_counter()-began
    allocated = torch.cuda.memory_allocated()-before
    predictions = []
    for text in ["01.09.2024", "30.06.2026", "УЧ-9651", "ИТ-89"]:
        image = Image.new("L", (400, 64), "white")
        ImageDraw.Draw(image).text((8, 8), text, font=ImageFont.truetype(font_path(), 32), fill="black")
        result = reader.recognize(np.asarray(image), decoder="greedy", detail=1)
        predictions.append({"expected": text, "actual": result[0][1]})
    return {"detector": detector, "startup_seconds": startup, "allocated_gpu_tensor_bytes": allocated,
            "predictions": predictions, "cuda_device": torch.cuda.get_device_name(0)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["full", "recognizer"])
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(one(args.worker == "full")), flush=True)
        return
    rows = []
    for mode in ["full", "recognizer", "recognizer", "full"]:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode], check=True, capture_output=True, text=True, encoding="utf-8")
        rows.append(json.loads(result.stdout.strip().splitlines()[-1]))
    import statistics
    summary = {str(flag): {"median_startup_seconds": statistics.median(r["startup_seconds"] for r in rows if r["detector"] == flag),
                          "median_gpu_tensor_bytes": statistics.median(r["allocated_gpu_tensor_bytes"] for r in rows if r["detector"] == flag)} for flag in [True, False]}
    signatures = [[r["actual"] for r in row["predictions"]] for row in rows]
    report = {"scope": "Four separate processes, alternating order. Torch/CUDA initialized before timing, OS file cache not flushed. GPU memory is live PyTorch tensors, excludes CUDA context and other processes. Four controlled crop readings; full suites are separate.",
              "rows": rows, "summary": summary, "same_predictions": all(s == signatures[0] for s in signatures)}
    (ROOT/"artifacts/ocr_reader_performance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)


if __name__ == "__main__":
    main()
