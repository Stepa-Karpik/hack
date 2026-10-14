"""Separate fixed192-train schema-value FP32/1MP language-only experiment."""
import argparse
import hashlib
import json
import random
import time
from pathlib import Path
from types import SimpleNamespace
from scripts.unified.train_literal_ocr import LANGUAGE_TARGET, language_module, native_inputs, infer
from scripts.unified.model import read_image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prediction_positions(labels):
    """Only assistant labels participate; preceding logits predict each label."""
    import torch
    indexes = torch.nonzero(labels[0] != -100, as_tuple=False).flatten()
    if not len(indexes) or int(indexes.min()) < 1:
        raise ValueError('Assistant targets must follow a nonempty prompt')
    return indexes - 1, labels[:, indexes]


def main():
    import numpy as np
    import torch
    from peft import LoraConfig, get_peft_model
    from safetensors.torch import load_file
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.graphic_head import GraphicReadout, pool_visual
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--graphic-inputs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=96)
    args = p.parse_args()
    if args.output.exists() or args.steps != 96:
        raise ValueError('Fresh output and bounded steps required')
    args.output.mkdir(parents=True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.manual_seed(42)
    random.seed(42)
    if not torch.cuda.is_available():
        raise ValueError('CUDA required')
    base_sha = sha(args.base / 'model.safetensors')
    head_sha = sha(args.head / 'graphic_head.safetensors')
    if base_sha != '85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db' or head_sha != '22c74e0cbc429c1c5db60df941a3c209043f4932265458f6c91909f21b871f04':
        raise ValueError('Immutable foundation/head identity mismatch')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    processor.image_processor.size.longest_edge = 1003520
    core, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.float32, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys']):
        raise ValueError('Incomplete native base')
    core = core.to('cuda').eval()
    head_config = json.loads((args.head / 'config.json').read_text(encoding='utf-8'))
    head = GraphicReadout(head_config['dimension'])
    head.load_state_dict(load_file(str(args.head / 'graphic_head.safetensors')))
    head = head.cuda().eval().requires_grad_(False)
    net = SimpleNamespace(model=core, processor=processor, torch=torch, device='cuda')
    visual_before = {n: hashlib.sha256(p.detach().cpu().numpy().tobytes()).hexdigest()
                     for n, p in core.named_parameters() if '.visual.' in '.' + n}

    def graphic_features():
        rows, arrays = [], {}
        for i, file in enumerate(args.graphic_inputs):
            batch = native_inputs(net, read_image(file))
            with torch.inference_mode():
                visual = net.model.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
                features = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
                scores = head(features).sigmoid()
            arrays['feature_' + str(i)] = features.cpu().numpy().copy()
            rows.append({'file': file.name, 'input_sha256': sha(file), 'scores': scores.tolist(),
                         'marks': [v >= .5 for v in scores.tolist()], 'grid': batch['image_grid_thw'].tolist()})
            del batch, visual, features, scores
        return rows, arrays

    before_rows, before_arrays = graphic_features()
    np.savez_compressed(args.output / 'graphic-before.npz', **before_arrays)
    (args.output / 'graphic-before.json').write_text(json.dumps({'complete': True, 'rows': before_rows}, indent=2), encoding='utf-8')
    modules = [n for n, _ in core.named_modules() if language_module(n)]
    if len(modules) != 36 or any('visual' in n for n in modules):
        raise ValueError('Unexpected language q/v module set')
    wrapped = get_peft_model(core, LoraConfig(r=8, lora_alpha=16, lora_dropout=.05,
                         target_modules=LANGUAGE_TARGET, task_type='CAUSAL_LM'))
    # Use native core with injected modules; avoid wrapper argument adaptation.
    net.model = wrapped.get_base_model()
    parameters = [v for n, v in wrapped.named_parameters() if v.requires_grad]
    if sum(v.numel() for v in parameters) != 626688 or any('language_model' not in n or 'lora_' not in n for n,v in wrapped.named_parameters() if v.requires_grad):
        raise ValueError('Only 626688 language LoRA parameters may be trained')
    config = dict(task='OCR:', precision='float32', max_pixels=1003520, rank=8, alpha=16, dropout=.05,
                  steps=args.steps, optimizer='AdamW', lr=5e-6, weight_decay=.01, warmup=8, accumulation=2,
                  seed=42, trainable_parameters=626688, max_training_tokens=4096,
                  train_records=192, heldout_images_each=48, checkpoint_every=48,
                  planned_train_coverage='One seeded shuffle; 192 microbatches / 96 optimizer steps',
                  cuda_matmul_allow_tf32=False, cudnn_allow_tf32=False,
                  base_sha256=base_sha, head_sha256=head_sha, vision_trainable=0, head_trainable=0,
                  memory_guard_bytes=7800000000, data_manifest_sha256=sha(args.data / 'manifest.json'),
                  runner_sha256=sha(Path(__file__)), promoted=False,
                  loss='Exact assistant next-token cross entropy; compute lm_head only at nonmasked prediction positions, no prompt logits/truncation')
    (args.output / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    wrapped.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    core.config.use_cache = False
    wrapped.train()
    core.model.visual.eval()
    if {str(v.dtype) for v in wrapped.parameters()} != {'torch.float32'}:
        raise ValueError('FP32-only parameters required')
    train = [json.loads(line) for line in (args.data / 'train.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(train) != 192 or any(r['seed'] not in range(202661000, 202661192) for r in train):
        raise ValueError('Only original new192 v4 training records allowed')
    if len({r['sha256'] for r in train}) != 192:
        raise ValueError('Unique fixed training pixels required')
    random.shuffle(train)
    used = []
    optimizer = torch.optim.AdamW(parameters, lr=5e-6, weight_decay=.01)
    history = []
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        for step in range(args.steps):
            optimizer.zero_grad(set_to_none=True)
            losses = []
            for micro in range(2):
                row = train[(2 * step + micro) % len(train)]
                file = args.data / row['image']
                if sha(file) != row['sha256']:
                    raise ValueError('Training image changed')
                batch = native_inputs(net, read_image(file), row['target_text'])
                labels = batch.pop('labels')
                positions, targets = prediction_positions(labels)
                used.append(dict(step=step+1, micro=micro, input_sha256=row['sha256'],
                                 image=row['image'], tokens=int(batch['input_ids'].shape[1]),
                                 assistant_target_tokens=int(targets.numel())))
                result = core(**batch, logits_to_keep=positions, use_cache=False)
                loss = torch.nn.functional.cross_entropy(result.logits.reshape(-1, result.logits.shape[-1]), targets.reshape(-1))
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite loss')
                (loss / 2).backward()
                losses.append(float(loss.detach()))
                if torch.cuda.max_memory_allocated() > config['memory_guard_bytes']:
                    raise ValueError('GPU memory guard exceeded; no automatic precision fallback')
                del batch, labels, positions, targets, result, loss
            for group in optimizer.param_groups:
                group['lr'] = 5e-6 * min(1., (step + 1) / 8)
            torch.nn.utils.clip_grad_norm_(parameters, 1.)
            optimizer.step()
            history.append(dict(step=step+1, loss=sum(losses)/2, seconds=time.perf_counter()-started,
                                peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated()))
            (args.output / 'training.json').write_text(json.dumps({'complete':step+1==args.steps, 'history':history}, indent=2), encoding='utf-8')
            print(json.dumps(history[-1]), flush=True)
            if (step + 1) % 48 == 0 or step + 1 == args.steps:
                wrapped.save_pretrained(args.output / f'step-{step+1:04d}')
    except Exception as error:
        (args.output / 'train-coverage-partial.json').write_text(json.dumps({'complete':False,'rows':used},indent=2),encoding='utf-8')
        (args.output / 'failure.json').write_text(json.dumps({'complete': False, 'type': type(error).__name__, 'error': str(error), 'completed_steps': len(history)}, indent=2), encoding='utf-8')
        raise
    del optimizer
    if len(used) != 192 or len({r['input_sha256'] for r in used}) != 192:
        raise ValueError('One full train-only rehearsal pass required')
    (args.output / 'train-coverage.json').write_text(json.dumps({'complete':True,'rows':used},indent=2),encoding='utf-8')
    core.config.use_cache = True
    wrapped.eval()
    actual = dict(core.named_parameters())
    if not visual_before or any(hashlib.sha256(actual[n].detach().cpu().numpy().tobytes()).hexdigest() != h for n,h in visual_before.items()):
        raise ValueError('Frozen visual parameter retention failed')
    after_rows, after_arrays = graphic_features()
    np.savez_compressed(args.output / 'graphic-after.npz', **after_arrays)
    features_equal = all(np.array_equal(before_arrays[k], after_arrays[k]) for k in before_arrays)
    scores_equal = before_rows == after_rows
    if not features_equal or not scores_equal or sha(args.head / 'graphic_head.safetensors') != head_sha:
        raise ValueError('Graphic features/head scores changed')
    (args.output / 'graphic-retention.json').write_text(json.dumps({'complete': True, 'rows': after_rows,
        'visual_parameters_equal': len(visual_before), 'features_exactly_equal': features_equal,
        'scores_exactly_equal': scores_equal, 'head_sha256_unchanged': head_sha}, indent=2), encoding='utf-8')
    # Image paths only. Held-out target files remain unopened until standalone grading.
    for split in ['val', 'test']:
        images = sorted(args.data.glob(split + '-[0-9][0-9][0-9].png'))
        if len(images) != 48:
            raise ValueError('Expected48 held-out images')
        rows = []
        for file in images:
            rows.append(infer(net, file, 768))
            report = dict(complete=len(rows)==48, rows=rows, precision='fp32', device='cuda',
                          max_pixels=1003520, max_tokens=768, parameter_dtypes=['torch.float32'],
                          cuda_matmul_allow_tf32=False, cudnn_allow_tf32=False,
                          actual_base_weight_sha256=base_sha,
                          adapter_sha256=sha(args.output/'step-0096/adapter_model.safetensors'),
                          scope='Image-only new synthetic OCR; targets unopened; not app/server qualification')
            (args.output / f'{split}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(split, len(rows), flush=True)


if __name__ == '__main__':
    main()
