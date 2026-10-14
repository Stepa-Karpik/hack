"""Language-only LoRA v5: continue adapter v4 on natural-page v5 data + v4b rehearsal.

Hypothesis (fixed before fitting): residual errors concentrate on serif
glyph confusions and unseen letter sequences; real-distribution surnames,
natural prose and ~20 more font families should reduce errors on *held-out*
font families and real pages without losing schema values. Strict FP32/1MP,
TF32 off, vision and graphic head frozen and verified bit-exact.
"""
import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path
from types import SimpleNamespace

from scripts.unified.model import read_image
from scripts.unified.train_literal_ocr import native_inputs
from scripts.unified.train_literal_values_fp32 import prediction_positions


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def v5_target(row, convention):
    """Rebuild target text from rendered lines under the probed native convention."""
    if convention == 'lines':
        return '\n'.join(row['lines'])
    # 'paragraphs' (probed native behaviour): wrapped lines of one block/column are
    # joined with a space; separate blocks are separated by one blank line.
    out, prev = [], None
    for line, (block, kind, column) in zip(row['lines'], row['line_blocks']):
        token = (block, column)
        if out and token == prev:
            out[-1] += ' ' + line
        else:
            out.append(line)
        prev = token
    return '\n\n'.join(out)


def main():
    import numpy as np
    import torch
    from peft import PeftModel
    from safetensors.torch import load_file
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.graphic_head import GraphicReadout, pool_visual
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--init-adapter', type=Path, required=True)
    p.add_argument('--v5', type=Path, required=True)
    p.add_argument('--v4b', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--graphic-inputs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--convention', choices=['lines', 'paragraphs'], required=True)
    p.add_argument('--steps', type=int, default=240)
    p.add_argument('--lr', type=float, default=2e-5)
    p.add_argument('--rehearsal', type=int, default=120)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    args.output.mkdir(parents=True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.manual_seed(42)
    rng = random.Random(42)
    base_sha = sha(args.base / 'model.safetensors')
    head_sha = sha(args.head / 'graphic_head.safetensors')
    init_sha = sha(args.init_adapter / 'adapter_model.safetensors')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    processor.image_processor.size.longest_edge = 1003520
    core = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False,
                                                       dtype=torch.float32, attn_implementation='sdpa').to('cuda')
    head_config = json.loads((args.head / 'config.json').read_text(encoding='utf-8'))
    head = GraphicReadout(head_config['dimension'])
    head.load_state_dict(load_file(str(args.head / 'graphic_head.safetensors')))
    head = head.cuda().eval().requires_grad_(False)
    visual_before = {n: hashlib.sha256(v.detach().cpu().numpy().tobytes()).hexdigest()
                     for n, v in core.named_parameters() if '.visual.' in '.' + n}
    net = SimpleNamespace(model=core.eval(), processor=processor, torch=torch, device='cuda')

    def graphic_features():
        rows, arrays = [], {}
        for i, file in enumerate(args.graphic_inputs):
            batch = native_inputs(net, read_image(file))
            with torch.inference_mode():
                visual = net.model.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
                features = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
                scores = head(features).sigmoid()
            arrays['feature_' + str(i)] = features.cpu().numpy().copy()
            rows.append({'file': str(file), 'input_sha256': sha(file), 'scores': scores.tolist(),
                         'marks': [v >= .5 for v in scores.tolist()]})
        return rows, arrays

    before_rows, before_arrays = graphic_features()
    np.savez_compressed(args.output / 'graphic-before.npz', **before_arrays)
    wrapped = PeftModel.from_pretrained(core, str(args.init_adapter), is_trainable=True)
    net.model = wrapped.get_base_model()
    parameters = [v for n, v in wrapped.named_parameters() if v.requires_grad]
    if sum(v.numel() for v in parameters) != 626688 or any('lora_' not in n or 'language_model' not in n
                                                           for n, v in wrapped.named_parameters() if v.requires_grad):
        raise ValueError('Only the 626688 language LoRA parameters may train')
    v5 = [json.loads(l) for l in (args.v5 / 'train.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    v4b = [json.loads(l) for l in (args.v4b / 'train.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    rehearsal = rng.sample(v4b, args.rehearsal)
    records = [dict(source='v5', file=str(args.v5 / r['image']), sha256=r['sha256'], target=v5_target(r, args.convention)) for r in v5]
    records += [dict(source='v4b', file=str(args.v4b / r['image']), sha256=r['sha256'], target=r['target_text']) for r in rehearsal]
    rng.shuffle(records)
    if len(records) != 2 * args.steps:
        raise ValueError('Plan: exactly one pass, two microbatches per optimizer step')
    config = dict(hypothesis=__doc__.strip(), init_adapter=str(args.init_adapter), init_adapter_sha256=init_sha,
                  base_sha256=base_sha, head_sha256=head_sha, precision='float32', max_pixels=1003520,
                  tf32=False, rank=8, alpha=16, dropout=.05, target='language q/v', trainable_parameters=626688,
                  steps=args.steps, accumulation=2, lr=args.lr, schedule='linear warmup 16 then cosine to 0.1x',
                  weight_decay=.01, clip=1., seed=42, v5_train=len(v5), v4b_rehearsal=len(rehearsal),
                  convention=args.convention, checkpoints=[80, 160, 240], vision_trainable=0, head_trainable=0,
                  heldout_never_read=['v5 val/test targets', 'v4b val/test', 'organizer kit', 'MWS eval'],
                  data_manifest_sha256=sha(args.v5 / 'manifest.json'), runner_sha256=sha(__file__), promoted=False)
    (args.output / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    wrapped.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    core.config.use_cache = False
    wrapped.train()
    core.model.visual.eval()
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=.01)
    torch.cuda.reset_peak_memory_stats()
    history, used, skipped = [], [], []
    started = time.perf_counter()
    for step in range(args.steps):
        lr = args.lr * min(1., (step + 1) / 16) if step < 16 else \
            args.lr * (.1 + .9 * .5 * (1 + math.cos(math.pi * (step - 16) / max(1, args.steps - 16))))
        for group in optimizer.param_groups:
            group['lr'] = lr
        optimizer.zero_grad(set_to_none=True)
        losses = []
        for micro in range(2):
            row = records[2 * step + micro]
            if sha(row['file']) != row['sha256']:
                raise ValueError('Training image changed')
            try:
                batch = native_inputs(net, read_image(row['file']), row['target'])
            except ValueError as error:
                skipped.append({'file': row['file'], 'reason': str(error)})
                continue
            labels = batch.pop('labels')
            positions, targets = prediction_positions(labels)
            result = core(**batch, logits_to_keep=positions, use_cache=False)
            loss = torch.nn.functional.cross_entropy(result.logits.reshape(-1, result.logits.shape[-1]), targets.reshape(-1))
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite loss')
            (loss / 2).backward()
            losses.append(float(loss.detach()))
            used.append({'step': step + 1, 'source': row['source'], 'file': row['file'], 'sha256': row['sha256'],
                         'tokens': int(batch['input_ids'].shape[1]), 'target_tokens': int(targets.numel())})
            if torch.cuda.max_memory_allocated() > 7_800_000_000:
                raise ValueError('GPU memory guard exceeded')
            del batch, labels, positions, targets, result, loss
        torch.nn.utils.clip_grad_norm_(parameters, 1.)
        optimizer.step()
        history.append({'step': step + 1, 'lr': lr, 'loss': sum(losses) / max(1, len(losses)),
                        'seconds': round(time.perf_counter() - started, 2), 'peak_bytes': torch.cuda.max_memory_allocated()})
        print(json.dumps(history[-1]), flush=True)
        (args.output / 'training.json').write_text(json.dumps({'complete': step + 1 == args.steps, 'history': history,
                                                              'skipped': skipped}, indent=1), encoding='utf-8')
        if (step + 1) in (80, 160, 240) or step + 1 == args.steps:
            wrapped.save_pretrained(args.output / f'step-{step + 1:04d}')
    (args.output / 'train-coverage.json').write_text(json.dumps({'rows': used, 'skipped': skipped}, indent=1), encoding='utf-8')
    wrapped.eval()
    core.config.use_cache = True
    actual = dict(core.named_parameters())
    if any(hashlib.sha256(actual[n].detach().cpu().numpy().tobytes()).hexdigest() != h for n, h in visual_before.items()):
        raise ValueError('Frozen visual parameters changed')
    after_rows, after_arrays = graphic_features()
    equal = all(np.array_equal(before_arrays[k], after_arrays[k]) for k in before_arrays)
    if not equal or before_rows != after_rows or sha(args.head / 'graphic_head.safetensors') != head_sha:
        raise ValueError('Graphic features/scores changed')
    (args.output / 'graphic-retention.json').write_text(json.dumps({'complete': True, 'visual_parameters_equal': len(visual_before),
        'features_exactly_equal': equal, 'scores_exactly_equal': True, 'rows': after_rows}, indent=1), encoding='utf-8')
    print('TRAINING_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
