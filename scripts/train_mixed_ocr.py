"""Isolated real-crop experiment with synthetic replay and per-group holdouts."""
import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import ConcatDataset, DataLoader, Dataset
from easyocr.recognition import NormalizePAD
from easyocr.easyocr import imgH

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.ocr import _get_reader
from dekanat.schema import ROOT
from scripts.train_ocr import Crops, evaluate


def read_verified_manifest(path, character):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted, documents, images = [], {}, set()
    for row in rows:
        if row.get("approved") is not True:
            continue
        split = row["split"]
        if split not in {"train", "validation", "test"}:
            raise ValueError("Unknown split")
        image = Path(row["image"])
        if not image.is_absolute():
            image = path.parent/image
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != row["crop_sha256"]:
            raise ValueError("Reviewed crop changed")
        if digest in images:
            raise ValueError("Duplicate crop")
        images.add(digest)
        document = row["document_sha256"]
        if document in documents and documents[document] != split:
            raise ValueError("Source document crosses splits")
        documents[document] = split
        text = row["text"]
        if not text.strip() or any(c not in character for c in text):
            raise ValueError("Empty or unsupported transcription; do not silently remove characters")
        accepted.append({**row, "image": str(image)})
    for split in ["train", "validation", "test"]:
        if not any(r["split"] == split for r in accepted):
            raise ValueError(f"No approved {split} crops")
    return accepted


class RealCrops(Dataset):
    def __init__(self, rows, split, augment=False):
        self.rows = [r for r in rows if r["split"] == split]
        self.pad = NormalizePAD((1, imgH, 512))
        self.augment = augment

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        image = Image.open(row["image"]).convert("L")
        width = math.ceil(imgH*image.width/image.height)
        if width > 512:
            raise ValueError("Crop too long for recognizer: recrop or use a wider architecture")
        if self.augment:
            # Modest contrast variation; preserve handwritten stroke geometry.
            from PIL import ImageEnhance
            image = ImageEnhance.Contrast(image).enhance(random.uniform(.85, 1.15))
        return self.pad(image.resize((width, imgH), Image.Resampling.BICUBIC)), row["text"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--synthetic-count", type=int, default=1200)
    parser.add_argument("--lr", type=float, default=1e-5)
    args = parser.parse_args()
    if args.output.resolve() == (ROOT/"models/ocr_cyrillic.pt").resolve():
        raise ValueError("Experiments must use a separate candidate output")
    if args.output.exists():
        raise ValueError("Candidate output already exists; choose a new experiment name")
    random.seed(20261012)
    torch.manual_seed(20261012)
    torch.set_num_threads(4)
    start = time.perf_counter()
    weights = ROOT/"models/ocr_cyrillic.pt"
    starting_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
    reader = _get_reader(True, str(weights), weights.stat().st_mtime)
    model = getattr(reader.recognizer, "module", reader.recognizer)
    rows = read_verified_manifest(args.manifest, reader.character)
    real_train = RealCrops(rows, "train", True)
    train = DataLoader(ConcatDataset([Crops(args.synthetic_count, 20261013, reader.character), real_train]), batch_size=32, shuffle=True)
    validation = {"synthetic": DataLoader(Crops(480, 73001, reader.character, True), batch_size=32),
                  "real": DataLoader(RealCrops(rows, "validation"), batch_size=32)}
    test = DataLoader(RealCrops(rows, "test"), batch_size=32)
    def metrics():
        return {name: evaluate(model, loader, reader.converter, reader.device) for name, loader in validation.items()}
    before = metrics()
    test_before = evaluate(model, test, reader.converter, reader.device)
    for parameter in model.FeatureExtraction.parameters():
        parameter.requires_grad = False
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=1e-5)
    loss_function = torch.nn.CTCLoss(blank=0, zero_infinity=True)
    best_score = float("inf")
    best_state, best_metrics, history = None, None, []
    for epoch in range(args.epochs):
        model.train()
        model.FeatureExtraction.eval()
        total_loss = 0
        for x, texts in train:
            optimizer.zero_grad(set_to_none=True)
            targets, lengths = reader.converter.encode(texts)
            logits = model(x.to(reader.device), None).log_softmax(2)
            input_lengths = torch.IntTensor([logits.shape[1]]*len(texts))
            loss = loss_function(logits.permute(1, 0, 2), targets.to(reader.device), input_lengths.to(reader.device), lengths.to(reader.device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            total_loss += float(loss.detach())
        current = metrics()
        score = sum(group["cer"] for group in current.values())/len(current)
        row = {"epoch": epoch+1, "loss": total_loss/len(train), "validation": current}
        history.append(row)
        print(json.dumps(row), flush=True)
        if score < best_score:
            best_score, best_metrics = score, current
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    test_after = evaluate(model, test, reader.converter, reader.device)
    checks = {name: after["exact_match"] >= before[name]["exact_match"] and after["cer"] <= before[name]["cer"] for name, after in best_metrics.items()}
    checks["real_test"] = test_after["exact_match"] >= test_before["exact_match"] and test_after["cer"] <= test_before["cer"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": best_state, "character": reader.character, "base": "Existing deployed EasyOCR fine-tune", "validation": best_metrics}, args.output)
    assert starting_hash == hashlib.sha256(weights.read_bytes()).hexdigest(), "Production weights changed"
    report = {"scope": "Small reviewed handwritten crop experiment. Page-separated splits; writer independence unknown. Not end-to-end student-document quality.",
              "starting_weights_sha256": starting_hash, "candidate_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
              "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(), "counts": {s: sum(r["split"] == s for r in rows) for s in ["train", "validation", "test"]},
              "synthetic_replay": args.synthetic_count, "lr": args.lr, "baseline_validation": before, "history": history, "selected_validation": best_metrics,
              "baseline_test": test_before, "selected_test": test_after, "crop_gate": checks, "crop_gate_passed": all(checks.values()),
              "deployed": False, "production_weights_unchanged": True, "reason": "Candidate isolated. Deployment also requires full document/camera regression and sufficient real target coverage.", "seconds": time.perf_counter()-start}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "history"}), flush=True)


if __name__ == "__main__":
    main()
