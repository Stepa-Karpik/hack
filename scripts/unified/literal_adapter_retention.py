"""Fresh paired image-only OCR retention and shared graphic feature checks."""
import argparse
import json
from pathlib import Path
from scripts.unified.model import read_image
from scripts.unified.train_literal_ocr import infer, native_inputs


def main():
    import torch
    from peft import PeftModel
    from safetensors.torch import load_file
    from scripts.unified.paddle_model import PaddleDocumentModel
    from scripts.unified.graphic_head import pool_visual, GraphicReadout
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--adapter', type=Path, required=True)
    parser.add_argument('--head', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    net = PaddleDocumentModel(args.base, max_pixels=1003520)
    config = json.loads((args.head / 'config.json').read_text(encoding='utf-8'))
    head = GraphicReadout(config['dimension']).to('cuda').eval()
    head.load_state_dict(load_file(str(args.head / 'graphic_head.safetensors'), device='cuda'))
    baseline = [infer(net, path, 1024) for path in args.inputs]
    features = []
    with torch.inference_mode():
        for path in args.inputs:
            batch = native_inputs(net, read_image(path))
            visual = net.model.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            features.append(pool_visual(visual.last_hidden_state, batch['image_grid_thw']).cpu())
    net.model = PeftModel.from_pretrained(net.model, str(args.adapter), is_trainable=False).eval()
    after = []
    checks = []
    for i, path in enumerate(args.inputs):
        after.append(infer(net, path, 1024))
        with torch.inference_mode():
            batch = native_inputs(net, read_image(path))
            visual = net.model.get_base_model().get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
            actual = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
            equal = torch.equal(features[i], actual.cpu())
            before_scores = head(features[i].to('cuda')).sigmoid()
            after_scores = head(actual).sigmoid()
        checks.append({'input_sha256': after[-1]['input_sha256'], 'features_equal': equal,
                       'graphic_scores_equal': torch.equal(before_scores, after_scores),
                       'graphic_scores_uncalibrated': after_scores.tolist()})
        report = {'scope': 'Fresh same-base OCR retention; repeated encoder calls are diagnostic, not a speed/one-pass claim',
                  'complete': len(after) == len(args.inputs),
                  'before': {'complete': True, 'rows': baseline},
                  'after': {'complete': len(after) == len(args.inputs), 'rows': after},
                  'shared_graphic_checks': checks, 'promoted': False}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('retention', i + 1, 'features_equal', equal, flush=True)


if __name__ == '__main__':
    main()
