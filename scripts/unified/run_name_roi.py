"""Same-backbone ROI extension over frozen actual shared-reader predictions.

No participant manifest/reference/evaluator or expected word lists are read.
Stored main predictions are SHA-bound to uploads; all eligible names processed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.unified.model import read_document
from scripts.unified.name_roi import FIELDS, accept, value_crop
from scripts.participantkit.format_v1 import validate
from scripts.participantkit.service import load_config


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--inputs-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
    source = json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    if (not baseline['complete'] or baseline['base_revision'] != source['revision']
            or baseline['base_weight_sha256'] != source['files']['model.safetensors']['sha256']):
        raise ValueError('Complete same-foundation baseline required')
    import torch
    from PIL import Image
    from transformers import AutoProcessor, AutoModelForImageTextToText
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    core, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.bfloat16, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('Incomplete foundation')
    core = core.to('cuda').eval()
    def read(image, task, budget):
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image},
                     {'type': 'text', 'text': task}]}]
        batch = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to('cuda')
        with torch.inference_mode():
            generated = core.generate(**batch, max_new_tokens=budget, do_sample=False, use_cache=True)
        tokens = generated[0, batch['input_ids'].shape[-1]:]
        return {'raw': processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False),
                'tokens': len(tokens), 'truncated': len(tokens) >= budget}
    config = load_config()
    rows = []
    for original in baseline['rows']:
        paths = list(args.inputs_root.rglob(original['file'])) if Path(original['file']).name == original['file'] else []
        if len(paths) != 1 or not paths[0].resolve().is_relative_to(args.inputs_root.resolve()):
            raise ValueError('Unique input file inside root required')
        path = paths[0]
        if hashlib.sha256(path.read_bytes()).hexdigest() != original['input_sha256']:
            raise ValueError('Actual upload identity mismatch')
        row = copy.deepcopy(original)
        image = read_document(path)
        result = row['result']
        eligible = [] if result is None else [k for k in sorted(FIELDS) if k in result['fields']
            and result['audit'][k].get('status') == 'uncertain'
            and result['audit'][k].get('source') == 'single_network_ocr_explicit_label'
            and isinstance(result['fields'][k], str) and result['fields'][k] != 'не найдено']
        spotting = read(image, 'Spotting:', 512) if eligible else None
        evidence = []
        for field in eligible:
            crop, geometry = value_crop(image, spotting['raw'], field, truncated=spotting['truncated'])
            readings = []
            if crop is not None:
                for scale in (1, 2):
                    supplied = crop if scale == 1 else crop.resize((crop.width*2, crop.height*2), Image.Resampling.BICUBIC)
                    readings.append(read(supplied.convert('RGB'), 'OCR:', 128))
            old = result['fields'][field]
            proposal, reason = accept(old, result['audit'][field],
                [None if r['truncated'] else r['raw'] for r in readings])
            evidence.append({'field': field, 'previous': old, 'geometry': geometry,
                             'readings': readings, 'proposal': proposal, 'reason': reason})
            if proposal is not None:
                result['fields'][field] = proposal
                box = geometry['value_bbox_pixels']
                result['audit'][field] = {'status': 'uncertain', 'semantic_confidence': None,
                    'source_confidence': None, 'source': 'single_network_name_roi_consensus',
                    'bbox': [box[0]/image.width*1000, box[1]/image.height*1000,
                             box[2]/image.width*1000, box[3]/image.height*1000],
                    'coordinate_space': 'input_image_0_1000', 'geometry_verified': False,
                    'original_literal': old, 'correlated_views': True}
        if result is not None:
            result['validation'] = validate(result['fields'], result['document_type'], config)
        row['name_roi'] = {'eligible_fields': eligible, 'spotting': spotting, 'evidence': evidence}
        rows.append(row)
        report = {k: v for k, v in baseline.items() if k != 'rows'}
        report.update(scope='Frozen actual main shared-reader predictions + fresh same-foundation Spotting/ROI '
            'for all eligible names. No new main OCR/marks, no second network or expected targets. '
            'Two correlated gray1x/bicubic2x views; no independent accuracy claim.',
            baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
            complete=len(rows) == len(baseline['rows']), rows=rows, promoted=False)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(len(rows), 'of', len(baseline['rows']), 'eligible', len(eligible),
              'accepted', sum(e['proposal'] is not None for e in evidence), flush=True)


if __name__ == '__main__':
    main()
