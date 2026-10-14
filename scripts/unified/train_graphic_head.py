"""Fit a small readout on frozen shared-backbone features; train labels only."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--features', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--additional-train-data', type=Path, action='append', default=[])
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh head checkpoint required')
    import numpy as np
    import torch
    from safetensors.torch import save_file
    from scripts.unified.graphic_head import GraphicReadout
    torch.set_num_threads(2)
    torch.manual_seed(42)
    manifest = json.loads((args.features/'manifest.json').read_text(encoding='utf-8'))
    if not manifest['complete'] or manifest['trainable_backbone_parameters'] != 0:
        raise ValueError('Complete frozen extraction required')
    # No val/test targets or organizer references are opened during fitting.
    roots = [args.data] + args.additional_train_data
    annotations = {(root.name, r['sha256']): r for root in roots for r in
                   [json.loads(line) for line in (root/'train.jsonl').read_text(encoding='utf-8').splitlines()]}
    inputs, targets, masks = [], [], []
    for r in manifest['rows']:
        if r['partition'] != 'train':
            continue
        path = args.features/r['feature']
        if hashlib.sha256(path.read_bytes()).hexdigest() != r['feature_sha256']:
            raise ValueError('Frozen feature SHA mismatch')
        target = annotations[(r.get('dataset_id', args.data.name), r['sha256'])]['target']['fields']
        keys = ('signature_present', 'seal_present')
        if any(k in target and type(target[k]) is not bool for k in keys):
            raise ValueError('Boolean graphic supervision required')
        inputs.append(np.load(path, allow_pickle=False))
        targets.append([float(target.get(k, False)) for k in keys])
        masks.append([float(k in target) for k in keys])
    x = torch.from_numpy(np.stack(inputs))
    y, mask = torch.tensor(targets), torch.tensor(masks)
    if not torch.isfinite(x).all() or (mask.sum(0) == 0).any():
        raise ValueError('Finite features and both supervised mark classes required')
    head = GraphicReadout(x.shape[1])
    head.mean.copy_(x.mean(0))
    head.scale.copy_(x.std(0).clamp_min(.01))
    optimizer = torch.optim.AdamW(head.parameters(), lr=.003, weight_decay=.1)
    history = []
    # Fixed 200 steps and threshold .5 before any control labels are inspected.
    for step in range(200):
        optimizer.zero_grad(set_to_none=True)
        logits = head(x)
        loss = (torch.nn.functional.binary_cross_entropy_with_logits(logits, y, reduction='none')*mask).sum()/mask.sum()
        if not torch.isfinite(loss):
            raise RuntimeError('Nonfinite head loss')
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.)
        optimizer.step()
        if step % 20 == 0 or step == 199:
            history.append({'step': step+1, 'loss': float(loss.detach())})
    args.output.mkdir(parents=True)
    save_file(head.state_dict(), str(args.output/'graphic_head.safetensors'))
    config = {'format': 'one-backbone-graphic-readout-v1', 'dimension': x.shape[1],
        'architecture': 'same native Paddle vision encoder + existing OCR decoder + linear graphic readout',
        'pooling': 'preprojector 3x3 mean/max', 'base': 'PaddlePaddle/PaddleOCR-VL-1.6',
        'base_revision': manifest['base_revision'], 'base_weight_sha256': manifest['base_weight_sha256'],
        'feature_manifest_sha256': hashlib.sha256((args.features/'manifest.json').read_bytes()).hexdigest(),
        'training_annotation_sha256': hashlib.sha256((args.data/'train.jsonl').read_bytes()).hexdigest(),
        'additional_training_annotations': [{'dataset_id': r.name,
            'sha256': hashlib.sha256((r/'train.jsonl').read_bytes()).hexdigest()} for r in args.additional_train_data],
        'train_count': len(inputs), 'trainable_parameters': sum(p.numel() for p in head.parameters()),
        'backbone_frozen': True, 'steps': 200, 'optimizer': 'AdamW', 'lr': .003, 'weight_decay': .1,
        'train_only_standardization': True, 'seed': 42, 'threshold_fixed': .5,
        'score_calibrated': False, 'history': history, 'promoted': False}
    (args.output/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    head.eval()
    predictions = []
    for r in manifest['rows']:
        path = args.features/r['feature']
        if hashlib.sha256(path.read_bytes()).hexdigest() != r['feature_sha256']:
            raise ValueError('Inference feature SHA mismatch')
        with torch.inference_mode():
            scores = head(torch.from_numpy(np.load(path, allow_pickle=False))).sigmoid().tolist()
        predictions.append({'image': r['image'], 'partition': r['partition'], 'sha256': r['sha256'],
            'dataset_id': r.get('dataset_id', args.data.name),
            'scores': scores, 'prediction': {k: s >= .5 for k, s in zip(('signature_present', 'seal_present'), scores)}})
    (args.output/'predictions.json').write_text(json.dumps({'scope': 'Cached frozen vision feature readout; '
        'not live complete application or independent real accuracy; scores uncalibrated',
        'complete': True, 'rows': predictions, 'promoted': False}, indent=2), encoding='utf-8')
    print('trained', len(inputs), 'pages;', config['trainable_parameters'], 'head parameters; no backbone training')


if __name__ == '__main__':
    main()
