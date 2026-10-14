"""Score images with the patch head and the existing global head (evaluation only)."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--images', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    import torch
    from scripts.unified.graphic_head import pool_visual
    from scripts.unified.model import read_document
    from scripts.unified.native_worker import Reader
    from scripts.unified.train_mark_patches import CLASSES, PatchHead, decode_maps, patch_inputs
    reader = Reader('work/paddle-vl-base-v1', 'models/unified-experimental-graphic-head-fp32-v3',
                    'models/unified-experimental-natural-v5', 'cuda', 6, swap=False)
    saved = torch.load(args.head, map_location='cuda')
    head = PatchHead.build(saved['dimension'], saved['hidden']).cuda()
    head.load_state_dict(saved['state_dict']); head.eval()
    rows = []
    for path in args.images:
        image = read_document(path)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
        batch = reader.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True,
            return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': reader.processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to('cuda')
        with torch.inference_mode():
            visual = reader.core.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            old = reader.head(pool_visual(visual.last_hidden_state, batch['image_grid_thw']).to('cuda')).sigmoid().tolist()
            x, h, w = patch_inputs(visual.last_hidden_state, batch['image_grid_thw'])
            maps = decode_maps(head(x), h, w)
        rows.append({'image': str(path), 'old': dict(zip(CLASSES, old)),
                     'new': {k: {'score': maps[k][0], 'box': maps[k][1]} for k in CLASSES}})
        print(Path(path).name, {k: round(v, 3) for k, v in rows[-1]['old'].items()}, {k: round(maps[k][0], 3) for k in CLASSES}, flush=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
