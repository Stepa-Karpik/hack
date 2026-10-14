"""One native foundation, image-only graphic-question diagnostic, no answers.

This does not infer a mark from OCR words. Only an exact complete boolean JSON
object is accepted; unknown/invalid generations remain unknown, never false.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from scripts.unified.model import read_document

PROMPT = ('Inspect only graphic elements in this document image. Is a drawn or handwritten '
          'signature visible? Is a graphic seal or stamp visible? Printed captions such as '
          'Подпись and М.П., empty lines, printed names and logos are not these marks. '
          'Return ONLY JSON with exactly two boolean keys: signature_present and seal_present.')


def parse_marks(text):
    try:
        value = json.loads(text.strip())
        if (not isinstance(value, dict) or set(value) != {'signature_present', 'seal_present'}
                or any(type(v) is not bool for v in value.values())):
            return None
        return value
    except (ValueError, TypeError):
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--inputs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh report required')
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    if not torch.cuda.is_available():
        raise RuntimeError('GPU diagnostic required')
    source = json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    if source['repo'] != 'PaddlePaddle/PaddleOCR-VL-1.6':
        raise ValueError('Unexpected foundation')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    net, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=torch.bfloat16, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('Incomplete native weights')
    net = net.to('cuda').eval()
    rows = []
    for path in args.inputs:
        image = read_document(path)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': PROMPT}]}]
        batch = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 2007040}}}).to('cuda')
        start = time.perf_counter()
        with torch.inference_mode():
            output = net.generate(**batch, max_new_tokens=256, do_sample=False, use_cache=True)
        torch.cuda.synchronize()
        tokens = output[0, batch['input_ids'].shape[-1]:]
        raw = processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        truncated = int(tokens.shape[-1]) >= 256
        rows.append({'file': path.name, 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'raw': raw, 'prediction': None if truncated else parse_marks(raw),
                     'token_budget_reached': truncated, 'seconds': time.perf_counter()-start})
        args.output.write_text(json.dumps({'scope': 'Single native network generic graphic prompt diagnostic; not app accuracy or production',
            'complete': len(rows) == len(args.inputs), 'planned_count': len(args.inputs),
            'base_revision': source['revision'], 'weights_sha256': source['files']['model.safetensors']['sha256'],
            'max_pixels': 2007040, 'max_tokens': 256, 'precision': 'bf16', 'prompt': PROMPT,
            'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(), 'rows': rows, 'promoted': False},
            ensure_ascii=False, indent=2), encoding='utf-8')
        print(path.name, 'accepted', rows[-1]['prediction'] is not None, flush=True)


if __name__ == '__main__':
    main()
