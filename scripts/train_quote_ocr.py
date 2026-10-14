"""Train an isolated Cyrillic recognizer with two appended guillemet tokens."""
import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from torch.utils.data import ConcatDataset, DataLoader, Dataset
from easyocr.recognition import NormalizePAD
from easyocr.easyocr import imgH

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from dekanat.ocr import get_reader, extend_alphabet
from dekanat.synthetic import values, font_path
from scripts.train_ocr import Crops, evaluate


class QuoteCrops(Dataset):
    def __init__(self, count, seed, validation=False, fixed=False):
        self.rows = []
        rng = random.Random(seed)
        fonts = [p for p in ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/georgia.ttf"] if Path(p).exists()]
        if validation and Path("C:/Windows/Fonts/calibri.ttf").exists():
            fonts = ["C:/Windows/Fonts/calibri.ttf"]
        if not fonts:
            fonts = [font_path()]
        for _ in range(count):
            data = values(rng)
            institution = rng.choice(["АНО ВО", "ФГБОУ ВО", "ФГАОУ ВО"])+f' «{data["university"]}»'
            program = f'«{data["program"]}»'
            choices = [institution, program, f'по направлению подготовки {program}',
                       f'«{data["university"]}', data["university"]+'»', f'«{data["program"]}', data["program"]+'».',
                       f'«{rng.choice(["Северный", "Восточный", "Южный", "Центральный"])}»']
            text = rng.choice(choices)
            font = ImageFont.truetype(rng.choice(fonts), rng.randint(20, 34))
            box = font.getbbox(text)
            image = Image.new("L", (box[2]-box[0]+12, box[3]-box[1]+12), rng.randint(235, 255))
            ImageDraw.Draw(image).text((6-box[0], 6-box[1]), text, font=font, fill=rng.randint(0, 45))
            if rng.random() < .2:
                image = image.filter(ImageFilter.GaussianBlur(rng.uniform(.1, .5)))
            width = math.ceil(imgH*image.width/image.height)
            if width > (512 if fixed else 2048):
                continue
            self.rows.append((NormalizePAD((1, imgH, 512 if fixed else width))(image.resize((width, imgH), Image.Resampling.BICUBIC)), text))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--recipe", choices=["variable", "original-fixed"], default="variable")
    p.add_argument("--output", type=Path, default=ROOT/"models/candidates/ocr_quotes_new.pt")
    p.add_argument("--report", type=Path, default=ROOT/"artifacts/ocr_quotes_new_training.json")
    args = p.parse_args()
    if args.output.exists() or args.output.resolve() == (ROOT/"models/ocr_cyrillic.pt").resolve():
        raise ValueError("Separate new candidate path required")
    random.seed(20261016)
    torch.manual_seed(20261016)
    torch.set_num_threads(4)
    reader = get_reader(True, "candidate")
    model = getattr(reader.recognizer, "module", reader.recognizer)
    old_character = reader.character
    replay_validation = DataLoader(Crops(480, 73001, old_character, True), batch_size=32)
    baseline = evaluate(model, replay_validation, reader.converter, reader.device)
    base = ROOT/"models/ocr_cyrillic.pt"
    base_hash = hashlib.sha256(base.read_bytes()).hexdigest()
    extend_alphabet(reader, old_character+"«»")
    fixed = args.recipe == "original-fixed"
    quote_train = QuoteCrops(3000, 2026101600, fixed=fixed)
    quote_validation = QuoteCrops(400, 2026101601, True, fixed=fixed)
    quote_test = QuoteCrops(400, 2026101602, True, fixed=fixed)
    def collate(batch):
        width = math.ceil(max(x.shape[-1] for x, _ in batch)/4)*4
        return torch.stack([torch.nn.functional.pad(x, (0, width-x.shape[-1]), mode="replicate") for x, _ in batch]), [text for _, text in batch]
    validation = DataLoader(quote_validation, batch_size=32 if fixed else 16, collate_fn=None if fixed else collate)
    test = DataLoader(quote_test, batch_size=32 if fixed else 16, collate_fn=None if fixed else collate)
    train = DataLoader(ConcatDataset([Crops(1600, 2026101603, reader.character), quote_train]), batch_size=32 if fixed else 16, shuffle=True, collate_fn=None if fixed else collate)
    before_quotes = evaluate(model, validation, reader.converter, reader.device)
    for parameter in model.FeatureExtraction.parameters():
        parameter.requires_grad = False
    for layer in ([] if fixed else [m for m in model.FeatureExtraction.modules() if isinstance(m, torch.nn.Conv2d)][-2:]):
        for parameter in layer.parameters():
            parameter.requires_grad = True
    groups = [
        {"params": model.SequenceModeling.parameters(), "lr": 1e-5},
        {"params": model.Prediction.parameters(), "lr": 1e-4}]
    if not fixed:
        groups.append({"params": [p for p in model.FeatureExtraction.parameters() if p.requires_grad], "lr": 2e-6})
    optimizer = torch.optim.AdamW(groups, weight_decay=1e-5)
    loss_function = torch.nn.CTCLoss(blank=0, zero_infinity=True)
    history, best, state, selected = [], float("inf"), None, None
    began = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        model.FeatureExtraction.eval()
        loss_sum = 0
        for x, texts in train:
            optimizer.zero_grad(set_to_none=True)
            targets, lengths = reader.converter.encode(texts)
            logits = model(x.to(reader.device), None).log_softmax(2)
            input_lengths = torch.IntTensor([logits.shape[1]]*len(texts))
            loss = loss_function(logits.permute(1, 0, 2), targets.to(reader.device), input_lengths.to(reader.device), lengths.to(reader.device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            loss_sum += float(loss.detach())
        quotes = evaluate(model, validation, reader.converter, reader.device)
        replay = evaluate(model, replay_validation, reader.converter, reader.device)
        result = {"epoch": epoch+1, "loss": loss_sum/len(train), "quotes": quotes, "replay": replay}
        history.append(result)
        print(json.dumps(result), flush=True)
        score = quotes["cer"]+replay["cer"]
        if score < best:
            best, selected = score, result
            state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(state)
    test_metrics = evaluate(model, test, reader.converter, reader.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": state, "character": reader.character, "base": "Existing cyrillic_g2 fine-tune; appended guillemet CTC tokens", "validation": selected}, args.output)
    assert base_hash == hashlib.sha256(base.read_bytes()).hexdigest()
    report = {"scope": "Synthetic quote-bearing crops with held-out Calibri when available. Synthetic replay regression; not real handwriting/document accuracy.",
              "base_sha256": base_hash, "candidate_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(), "alphabet_extension": "«»", "seed": 20261016,
              "quote_train": len(quote_train), "quote_validation": len(quote_validation), "quote_test": len(quote_test), "synthetic_replay_train": 1600,
              "recipe": args.recipe, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "baseline_replay": baseline, "untrained_extended_alphabet_quotes": before_quotes, "history": history, "selected": selected, "test_quotes": test_metrics,
              "deployed": False, "base_weights_unchanged": True, "seconds": time.perf_counter()-began}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
