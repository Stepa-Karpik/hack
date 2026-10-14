"""Image-only frozen native feature extraction, never reads target fields."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.unified.model import read_image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--train-limit', type=int, default=120)
    p.add_argument('--additional-train-data', type=Path, action='append', default=[])
    args = p.parse_args()
    if args.output.exists() or not 1 <= args.train_limit <= 240:
        raise ValueError('Fresh bounded feature directory required')
    import torch
    import numpy as np
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.graphic_head import pool_visual
    source = json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    if source['repo'] != 'PaddlePaddle/PaddleOCR-VL-1.6' or not torch.cuda.is_available():
        raise ValueError('Pinned native CUDA foundation required')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    net, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.bfloat16, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('Incomplete native mapping')
    net = net.to('cuda').eval()
    for param in net.parameters():
        param.requires_grad_(False)
    args.output.mkdir(parents=True)
    inputs = []
    roots = [args.data] + args.additional_train_data
    if len({root.resolve() for root in roots}) != len(roots):
        raise ValueError('Duplicate dataset root')
    for root in roots:
        for split in (('train', 'val', 'test') if root == args.data else ('train',)):
            rows = [json.loads(line) for line in (root/(split+'.jsonl')).read_text(encoding='utf-8').splitlines()]
            rows = rows[:args.train_limit] if split == 'train' and root == args.data else rows
            for row in rows:
                # Additional-source val/test frames are never loaded or extracted.
                inputs.append({'dataset_id': root.name, 'partition': split, 'image': row['image'],
                               'sha256': row['sha256'], '_root': root})
    records = []
    for spec in inputs:
        root = spec['_root']
        path = (root/spec['image']).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != spec['sha256']:
            raise ValueError('Image identity mismatch')
        image = read_image(path)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
        batch = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to('cuda')
        with torch.inference_mode():
            visual = net.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            features = pool_visual(visual.last_hidden_state, batch['image_grid_thw']).cpu().numpy()
        file = args.output/f'{len(records):04d}.npy'
        np.save(file, features, allow_pickle=False)
        records.append({**{k: v for k, v in spec.items() if k != '_root'}, 'feature': file.name, 'feature_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                        'dimension': len(features), 'grid': batch['image_grid_thw'].tolist()})
        (args.output/'manifest.json').write_text(json.dumps({'scope': 'Frozen shared-backbone feature diagnostic, '
            'primary fictional split data; additional sources train-only, no independent real accuracy. No organizer controls.',
            'complete': len(records) == len(inputs), 'planned_count': len(inputs), 'rows': records,
            'base_revision': source['revision'], 'base_weight_sha256': source['files']['model.safetensors']['sha256'],
            'dtype': 'bfloat16', 'max_pixels': 1003520, 'pooling': 'preprojector 3x3 mean/max',
            'data_manifest_sha256': hashlib.sha256((args.data/'manifest.json').read_bytes()).hexdigest(),
            'additional_train_sources': [{'dataset_id': r.name,
                'manifest_sha256': hashlib.sha256((r/'manifest.json').read_bytes()).hexdigest(),
                'partitions_loaded': ['train']} for r in args.additional_train_data],
            'trainable_backbone_parameters': 0}, indent=2), encoding='utf-8')
        print(spec['partition'], spec['image'], 'features', len(features), flush=True)
        del batch, visual, features


if __name__ == '__main__':
    main()
