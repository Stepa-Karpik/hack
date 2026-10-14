"""Bounded image-only device/precision probe of one frozen native vision backbone.

No labels, OCR generation, reference lookup or threshold fitting. Feature arrays
are diagnostic outputs, not additional models or independent confidence views.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--inputs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--device', choices=['cpu', 'cuda'], required=True)
    p.add_argument('--precision', choices=['fp32', 'bf16'], default='fp32')
    p.add_argument('--tf32', choices=['off', 'on'], default='off')
    p.add_argument('--threads', type=int, default=6)
    args = p.parse_args()
    if not 1 <= args.threads <= 16 or not 1 <= len(args.inputs) <= 8:
        raise ValueError('Bounded threads and one to eight images required')
    arrays = args.output.with_suffix('.features.npz')
    if args.output.exists() or arrays.exists():
        raise ValueError('Fresh diagnostic outputs required')
    if args.device == 'cpu' and (args.precision != 'fp32' or args.tf32 != 'off'):
        raise ValueError('This bounded CPU diagnostic requires FP32/TF32 off')
    import numpy as np
    import torch
    from safetensors.torch import load_file
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.model import read_image
    from scripts.unified.graphic_head import GraphicReadout, pool_visual
    sha = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    array_sha = lambda value: hashlib.sha256(value.tobytes()).hexdigest()
    torch.set_num_threads(args.threads)
    torch.backends.cuda.matmul.allow_tf32 = args.tf32 == 'on'
    torch.backends.cudnn.allow_tf32 = args.tf32 == 'on'
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA unavailable')
    config = json.loads((args.head/'config.json').read_text(encoding='utf-8'))
    source = json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    base_sha = sha(args.base/'model.safetensors')
    if (not config['backbone_frozen'] or config['base_revision'] != source['revision']
            or config['base_weight_sha256'] != base_sha
            or source['files']['model.safetensors']['sha256'] != base_sha):
        raise ValueError('Actual frozen foundation identity mismatch')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    model, info = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.float32 if args.precision == 'fp32' else torch.bfloat16,
        attn_implementation='sdpa', output_loading_info=True)
    if any(info.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys']):
        raise ValueError('Incomplete native foundation')
    model = model.to(args.device).eval()
    head = GraphicReadout(config['dimension']).to(args.device).eval()
    head.load_state_dict(load_file(str(args.head/'graphic_head.safetensors'), device=args.device))
    rows, features, calls = [], {}, []
    hook = model.model.visual.register_forward_hook(lambda *unused: calls.append(1))
    for i, file in enumerate(args.inputs):
        image = read_image(file)
        batch = processor.apply_chat_template([{'role': 'user', 'content': [
            {'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}],
            add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors='pt',
            processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}})
        pixel_sha = array_sha(batch['pixel_values'].numpy())
        batch = batch.to(args.device)
        calls.clear()
        if args.device == 'cuda': torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            visual = model.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            pooled = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
            logits = head(pooled)
            scores = logits.sigmoid().cpu().tolist()
        if args.device == 'cuda': torch.cuda.synchronize()
        seconds = time.perf_counter()-started
        if len(calls) != 1: raise RuntimeError('Exactly one native vision pass required')
        values = pooled.cpu().numpy()
        features['feature_'+str(i)] = values
        rows.append({'file': file.name, 'input_sha256': sha(file), 'decoded_rgb_sha256':
            hashlib.sha256(image.tobytes()).hexdigest(), 'processor_pixels_sha256': pixel_sha,
            'image_grid_thw': batch['image_grid_thw'].cpu().tolist(), 'features_key': 'feature_'+str(i),
            'feature_sha256': array_sha(values), 'scores': scores, 'prediction':
            {k: s >= .5 for k, s in zip(['signature_present', 'seal_present'], scores)},
            'seconds_vision_head': seconds, 'visual_passes': len(calls)})
        np.savez_compressed(arrays, **features)
        args.output.write_text(json.dumps({'complete': len(rows) == len(args.inputs),
            'planned': len(args.inputs), 'rows': rows, 'device': args.device, 'precision': args.precision,
            'tf32_matmul_allowed': torch.backends.cuda.matmul.allow_tf32,
            'tf32_cudnn_allowed': torch.backends.cudnn.allow_tf32, 'threads': args.threads,
            'parameter_dtypes': sorted({str(v.dtype) for v in model.parameters()}),
            'base_revision': source['revision'], 'base_weight_sha256': base_sha,
            'head_sha256': sha(args.head/'graphic_head.safetensors'), 'features_sha256': sha(arrays),
            'threshold': .5, 'scores_calibrated': False, 'ocr_generated': False, 'promoted': False},
            indent=2), encoding='utf-8')
        print(args.device, args.precision, args.tf32, file.name, scores, flush=True)
    hook.remove()


if __name__ == '__main__':
    main()
