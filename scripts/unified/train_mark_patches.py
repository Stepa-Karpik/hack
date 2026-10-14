"""Patch-level signature/seal head on frozen PaddleOCR-VL vision features.

Same backbone and the same single visual pass as recognition; a small MLP scores
every native patch (feature + 3x3 neighbourhood mean) for signature and seal.
Presence = max smoothed patch probability; the box = connected patches around
the maximum. Trained only on train splits; thresholds chosen on val splits;
test splits, the organizer kit and real documents are evaluation only.
"""
import argparse
import hashlib
import json
import random
import time
from pathlib import Path

CLASSES = ('signature_present', 'seal_present')


class PatchHead:
    """Pure-torch module factory (kept importable without torch at module import)."""

    @staticmethod
    def build(dimension, hidden=128):
        import torch
        from torch import nn

        class Head(nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer('mean', torch.zeros(dimension * 2))
                self.register_buffer('scale', torch.ones(dimension * 2))
                self.net = nn.Sequential(nn.Linear(dimension * 2, hidden), nn.GELU(), nn.Linear(hidden, len(CLASSES)))

            def forward(self, x):
                return self.net((x - self.mean) / self.scale)
        return Head()


def patch_inputs(tokens, grid):
    """(h*w, D) native patch features -> (h*w, 2D) [feature, 3x3 neighbourhood mean]."""
    import torch
    h, w = int(grid[0, 1]), int(grid[0, 2])
    f = tokens.float().reshape(h, w, -1).permute(2, 0, 1).unsqueeze(0)
    neigh = torch.nn.functional.avg_pool2d(f, 3, stride=1, padding=1, count_include_pad=False)
    return torch.cat([f, neigh], 1).squeeze(0).permute(1, 2, 0).reshape(h * w, -1), h, w


def decode_maps(logits, h, w):
    """Smoothed probability maps -> per class (score, box in 0..1 or None)."""
    import torch
    prob = logits.sigmoid().T.reshape(len(CLASSES), 1, h, w)
    smooth = torch.nn.functional.avg_pool2d(prob, 3, stride=1, padding=1, count_include_pad=False)[:, 0]
    out = {}
    for c, name in enumerate(CLASSES):
        m = smooth[c]
        score = float(m.max())
        idx = int(m.argmax())
        y0, x0 = divmod(idx, w)
        keep = (prob[c, 0] > max(0.4, 0.6 * float(prob[c, 0].max()))).cpu()
        # flood fill the component containing the maximum
        seen, stack, cells = set(), [(y0, x0)], []
        while stack:
            y, x = stack.pop()
            if (y, x) in seen or not (0 <= y < h and 0 <= x < w) or not keep[y, x]:
                continue
            seen.add((y, x)); cells.append((y, x))
            stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1), (y + 1, x + 1), (y - 1, x - 1), (y + 1, x - 1), (y - 1, x + 1)]
        if cells:
            ys = [c[0] for c in cells]; xs = [c[1] for c in cells]
            box = [round(min(xs) / w, 4), round(min(ys) / h, 4), round((max(xs) + 1) / w, 4), round((max(ys) + 1) / h, 4)]
        else:
            box = [round(x0 / w, 4), round(y0 / h, 4), round((x0 + 1) / w, 4), round((y0 + 1) / h, 4)]
        out[name] = (score, box)
    return out


def labels_for(h, w, boxes_by_class):
    import torch
    ys = (torch.arange(h).float() + .5) / h
    xs = (torch.arange(w).float() + .5) / w
    Y, X = torch.meshgrid(ys, xs, indexing='ij')
    lab = torch.zeros(h * w, len(CLASSES))
    for c, name in enumerate(CLASSES):
        for b in boxes_by_class.get(name, []):
            inside = (X >= b[0]) & (X <= b[2]) & (Y >= b[1]) & (Y <= b[3])
            lab[:, c] = torch.maximum(lab[:, c], inside.reshape(-1).float())
    return lab


def cohorts(work):
    """(split, image path, boxes) from the new mark pages and the earlier boxed cohorts."""
    items = []
    for split in ('train', 'val', 'test'):
        for line in (work / 'marks-v1/data' / f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            items.append((split, 'marks-v1', work / 'marks-v1/data' / r['image'],
                          {'signature_present': r['signature'], 'seal_present': r['seal']}))
        for name in ('unified-data-v2', 'unified-real-marks-v1'):
            for line in (work / name / f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
                r = json.loads(line)
                t = r['target']
                boxes = {k: ([[v / 1000 for v in t['boxes'][k]]] if t['fields'].get(k) and t['boxes'].get(k) else [])
                         for k in CLASSES if k in t['fields']}
                items.append((split, name, work / name / r['image'], boxes))
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work', type=Path, default=Path('work'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=3000)
    args = p.parse_args()
    import numpy as np
    import torch
    from scripts.unified.native_worker import Reader
    from scripts.unified.model import read_image
    args.output.mkdir(parents=True, exist_ok=True)
    reader = Reader(args.work / 'paddle-vl-base-v1', 'models/unified-experimental-graphic-head-fp32-v3',
                    'models/unified-experimental-natural-v5', 'cuda', 6, swap=False)
    items = cohorts(args.work)

    def features(path):
        image = read_image(path)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
        batch = reader.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True,
            return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': reader.processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to('cuda')
        with torch.inference_mode():
            visual = reader.core.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            x, h, w = patch_inputs(visual.last_hidden_state, batch['image_grid_thw'])
        return x, h, w

    # 1) training patches: all positives + sampled negatives (more near marks)
    rng = random.Random(42)
    xs, ys = [], []
    started = time.perf_counter()
    train = [it for it in items if it[0] == 'train']
    for i, (split, cohort, path, boxes) in enumerate(train):
        t0 = time.perf_counter()
        x, h, w = features(path)
        t1 = time.perf_counter()
        lab = labels_for(h, w, boxes)
        pos = torch.nonzero(lab.sum(1) > 0).flatten().tolist()
        taken = set(pos)
        neg = [j for j in range(h * w) if j not in taken]
        neg = rng.sample(neg, min(len(neg), 700))
        idx = pos + neg
        xs.append(x[idx].cpu().half()); ys.append(lab[idx])
        if i % 25 == 0 or i < 5:
            print('train features', i, len(train), round(time.perf_counter() - started), 'vision', round(t1 - t0, 2),
                  'rest', round(time.perf_counter() - t1, 2), flush=True)
    X = torch.cat(xs).float().cuda(); Y = torch.cat(ys).cuda()
    print('patches', X.shape, 'positives', Y.sum(0).tolist(), flush=True)
    head = PatchHead.build(X.shape[1] // 2).cuda()
    head.mean.copy_(X.mean(0)); head.scale.copy_(X.std(0).clamp_min(1e-4))
    pos_weight = ((Y.shape[0] - Y.sum(0)) / Y.sum(0).clamp_min(1)).clamp(max=30)
    opt = torch.optim.AdamW(head.parameters(), lr=2e-3, weight_decay=1e-2)
    torch.manual_seed(42)
    for step in range(args.steps):
        batch = torch.randint(0, X.shape[0], (4096,), device='cuda')
        loss = torch.nn.functional.binary_cross_entropy_with_logits(head(X[batch]), Y[batch], pos_weight=pos_weight)
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 500 == 0:
            print('step', step, round(float(loss), 4), flush=True)
    head.eval()
    torch.save({'state_dict': head.state_dict(), 'dimension': X.shape[1] // 2, 'hidden': 128, 'classes': CLASSES},
               args.output / 'patch_head.pt')
    del X, Y

    # 2) score every val/test page (full maps) with the new head and the existing global head
    rows = []
    for split, cohort, path, boxes in [it for it in items if it[0] != 'train']:
        x, h, w = features(path)
        with torch.inference_mode():
            maps = decode_maps(head(x), h, w)
        rows.append({'split': split, 'cohort': cohort, 'image': str(path), 'truth': {k: bool(boxes.get(k)) for k in CLASSES},
                     'boxes': boxes, 'pred': {k: {'score': maps[k][0], 'box': maps[k][1]} for k in CLASSES}})
    (args.output / 'heldout-scores.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    print('DONE', len(rows), flush=True)


if __name__ == '__main__':
    main()
