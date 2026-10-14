"""Image-only mark readout precision gate, with no OCR generation or targets."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.unified.model import read_image


def main():
    import torch
    from safetensors.torch import load_file
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.graphic_head import pool_visual, GraphicReadout
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--head', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not torch.cuda.is_available():
        raise ValueError('Fresh CUDA output required')
    source = json.loads((args.base / 'source-manifest.json').read_text(encoding='utf-8'))
    config = json.loads((args.head / 'config.json').read_text(encoding='utf-8'))
    if config['base_weight_sha256'] != source['files']['model.safetensors']['sha256']:
        raise ValueError('Head foundation identity mismatch')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    model, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.float32, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('Incomplete native foundation')
    model = model.to('cuda').eval()
    head = GraphicReadout(config['dimension']).to('cuda').eval()
    head.load_state_dict(load_file(str(args.head / 'graphic_head.safetensors'), device='cuda'))
    rows = []
    for file in args.inputs:
        image = read_image(file)
        batch = processor.apply_chat_template([{'role': 'user', 'content': [
            {'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}],
            add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors='pt',
            processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to('cuda')
        with torch.inference_mode():
            visual = model.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            features = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
            scores = head(features).sigmoid().tolist()
        rows.append({'image': file.parent.name + '/' + file.name, 'partition': file.parent.name,
                     'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'scores': scores,
                     'prediction': {k: s >= .5 for k, s in zip(['signature_present', 'seal_present'], scores)},
                     'feature_sha256': hashlib.sha256(features.cpu().numpy().tobytes()).hexdigest()})
        args.output.write_text(json.dumps({'scope': 'Fresh FP32 shared vision/readout only; no OCR or full app qualification',
            'complete': len(rows) == len(args.inputs), 'rows': rows, 'max_pixels': 1003520,
            'head_sha256': hashlib.sha256((args.head / 'graphic_head.safetensors').read_bytes()).hexdigest(),
            'precision': 'fp32', 'threshold': .5, 'scores_calibrated': False, 'promoted': False}, indent=2), encoding='utf-8')
        print(file.parent.name, file.name, flush=True)


if __name__ == '__main__':
    main()
